#!/usr/bin/env python3
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import mimetypes
import os
import re
import shutil
import tarfile
import threading
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

ARCHIVE_SUFFIXES = (
    '.tar.gz', '.tar.bz2', '.tar.xz', '.tgz', '.tbz2', '.txz',
    '.zip', '.7z', '.rar', '.tar', '.gz', '.bz2', '.xz',
)
ACTIVE_ATTACHMENT_STATES = {'FETCHING', 'CHAT_UPLOADING', 'CLAUDE_UPLOADING'}
RETRYABLE_ATTACHMENT_STATES = {'ERROR', 'STALLED'}
READY_ATTACHMENT_STATES = {'UPLOADED'}
PENDING_ATTACHMENT_STATES = {'PENDING', 'RETRY_PENDING', 'RECOVER_PENDING'}
TERMINAL_JOB_STATES = {'SENT', 'CONSUMED', 'SUPERSEDED', 'CANCELLED'}

# Rollout modes for the breaking boundary.
#
#   OPEN    normal operation
#   DRAIN   no new work is handed out and no new claim may be taken; events for
#           work already claimed are still accepted so it can finish
#   BARRIER new delivery work is refused outright
#
# DRAIN is a pass with an identity of its own, not merely "there are no leases
# right now". A lease that existed and expired during the pass leaves an
# outcome nobody can report on, and an empty queue afterwards is not evidence
# that the outcome is known.
ROLLOUT_OPEN = 'OPEN'
ROLLOUT_DRAIN = 'DRAIN'
ROLLOUT_BARRIER = 'BARRIER'
ROLLOUT_MODES = (ROLLOUT_OPEN, ROLLOUT_DRAIN, ROLLOUT_BARRIER)
PAUSED_JOB_STATE = 'PAUSED_AFTER_RESTART'
NONTERMINAL_JOB_STATES = {
    'QUEUED', 'SEND_ERROR', 'SEND_REQUESTED', 'UPLOADING', 'PARTIAL',
    'READY_TO_SEND', 'FILES_READY',
}
KNOWN_JOB_STATES = TERMINAL_JOB_STATES | NONTERMINAL_JOB_STATES | {PAUSED_JOB_STATE}
CLAIM_LEASE_SECONDS = 15
MAX_AUTO_RECOVERIES = 3
SMART_ZIP_MAX_BYTES = 30 * 1024 * 1024
SMART_ZIP_SAFETY_BYTES = 64 * 1024


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def utc_now_dt() -> datetime:
    return datetime.now(timezone.utc)


def iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except Exception:
        return None


def decision_dt(value: Any) -> datetime | None:
    """A stored timestamp fit to take a decision on, or None for UNKNOWN.

    The project rule, applied in one place instead of at every call site: a
    stored time that takes part in a decision must be parseable and must carry
    an offset. Missing, malformed and naive all answer None here, and the
    caller decides what refusal means — never what default to substitute.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = iso_dt(value)
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def utc_after(seconds: int) -> str:
    return (utc_now_dt() + timedelta(seconds=int(seconds))).isoformat().replace('+00:00', 'Z')


def atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def safe_name(name: str) -> str:
    value = str(name or 'file.bin').replace('\\', '/').split('/')[-1].strip()
    value = re.sub(r'[\x00-\x1f\x7f]', '_', value)
    if not value or value in {'.', '..'}:
        value = 'file.bin'
    return value[:220]


def is_archive_name(name: str) -> bool:
    lower = str(name or '').lower()
    return any(lower.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)



def with_missing_suffix(message: str, missing: list[str]) -> str:
    text = re.sub(r'(?:\n\n)?Такие файлы отсутствуют: [^\n]*\s*$', '', str(message or '')).rstrip()
    rows = list(dict.fromkeys(str(x) for x in missing if str(x)))
    if not rows:
        return text
    suffix = 'Такие файлы отсутствуют: ' + ', '.join(rows)
    return (text + '\n\n' + suffix).strip() if text else suffix


def unique_path(directory: Path, name: str) -> Path:
    name = safe_name(name)
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    for idx in range(2, 10000):
        item = directory / f'{stem}-{idx}{suffix}'
        if not item.exists():
            return item
    raise RuntimeError('cannot allocate unique delivery filename')


class DeliveryError(RuntimeError):
    pass


class DeliveryManager:
    def __init__(
        self,
        root: Path,
        data_dir: Path,
        terminal_log_builder: Callable[[str], str],
        dispatch_epoch: str,
    ) -> None:
        self.root = root.resolve()
        self.data_dir = data_dir.resolve()
        self.terminal_log_builder = terminal_log_builder
        self.dispatch_epoch = str(dispatch_epoch or '')
        self.lock = threading.RLock()

    def run_dir(self, run_id: str) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,180}', str(run_id or '')):
            raise DeliveryError('invalid runId')
        path = (self.data_dir / run_id).resolve()
        if self.data_dir not in path.parents:
            raise DeliveryError('invalid run path')
        if not path.is_dir():
            raise DeliveryError('run not found')
        return path

    def delivery_root(self, run_id: str) -> Path:
        return self.run_dir(run_id) / 'executor' / 'delivery'

    def job_dir(self, run_id: str, job_id: str) -> Path:
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,180}', str(job_id or '')):
            raise DeliveryError('invalid jobId')
        root = self.delivery_root(run_id).resolve()
        path = (root / job_id).resolve()
        if root not in path.parents:
            raise DeliveryError('invalid job path')
        return path

    def job_path(self, run_id: str, job_id: str) -> Path:
        return self.job_dir(run_id, job_id) / 'job.json'

    def _load_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text('utf-8'))
        except Exception:
            return default

    @staticmethod
    def _file_sha256(path: Path) -> str:
        h = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _manifest_digest(manifest: dict[str, Any]) -> str:
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _logical_identity(run_id: str, side_effect_key: str | None = None,
                          logical_delivery_id: str | None = None) -> tuple[str, str]:
        side = str(side_effect_key or f'chat.send:{run_id}:primary').strip()
        if not side:
            raise DeliveryError('sideEffectKey is required')
        logical = str(logical_delivery_id or '').strip()
        if not logical:
            logical = 'ld-' + hashlib.sha256(side.encode('utf-8')).hexdigest()[:32]
        return logical, side

    def _build_delivery_manifest(self, *, delivery_id: str, logical_delivery_id: str,
                                 side_effect_key: str, delivery_session_id: str | None,
                                 target: dict[str, Any], message: str,
                                 attachments: list[dict[str, Any]]) -> dict[str, Any]:
        manifest_attachments = []
        for ordinal, attachment in enumerate(attachments, start=1):
            path = Path(str(attachment.get('path') or '')).resolve()
            if not path.is_file():
                raise DeliveryError(f'delivery attachment missing before manifest: {attachment.get("attachmentId")}')
            artifact_id = attachment.get('artifactId')
            if artifact_id is not None:
                artifact_id = str(artifact_id).strip() or None
            source_artifact_ids = attachment.get('sourceArtifactIds')
            if isinstance(source_artifact_ids, list):
                source_artifact_ids = [str(x).strip() for x in source_artifact_ids if str(x).strip()]
            else:
                source_artifact_ids = []
            manifest_attachments.append({
                'ordinal': ordinal,
                'attachmentId': str(attachment.get('attachmentId') or ''),
                'artifactId': artifact_id,
                'sourceArtifactIds': source_artifact_ids,
                'outgoingFilename': str(attachment.get('name') or ''),
                'size': int(attachment.get('size') if attachment.get('size') is not None else 0),
                'mimeType': str(attachment.get('mimeType') or ''),
                'sha256': self._file_sha256(path),
            })
        return {
            'schemaVersion': 1,
            'deliveryId': delivery_id,
            'logicalDeliveryId': logical_delivery_id,
            'sideEffectKey': side_effect_key,
            'deliverySessionId': delivery_session_id,
            'target': {
                'endpointId': str(target.get('endpointId') or ''),
                'browserEpoch': str(target.get('browserEpoch') or ''),
                'tabId': int(target.get('tabId')),
                'chatType': str(target.get('chatType') or ''),
                'conversationId': str(target.get('conversationId') or ''),
                'projectId': target.get('projectId'),
            },
            'message': str(message),
            'attachments': manifest_attachments,
        }

    def _manifest_error(self, job: dict[str, Any]) -> str:
        manifest = job.get('deliveryManifest')
        digest = job.get('deliveryManifestSha256')
        if not isinstance(manifest, dict):
            return 'deliveryManifest is not an object'
        if not isinstance(digest, str) or len(digest) != 64:
            return 'deliveryManifestSha256 is missing'
        if self._manifest_digest(manifest) != digest:
            return 'deliveryManifestSha256 does not match manifest bytes'
        if str(manifest.get('deliveryId') or '') != str(job.get('jobId') or ''):
            return 'manifest deliveryId differs from job'
        if str(manifest.get('logicalDeliveryId') or '') != str(job.get('logicalDeliveryId') or ''):
            return 'manifest logicalDeliveryId differs from job'
        if str(manifest.get('sideEffectKey') or '') != str(job.get('sideEffectKey') or ''):
            return 'manifest sideEffectKey differs from job'
        if (manifest.get('deliverySessionId') or None) != (job.get('deliverySessionId') or None):
            return 'manifest deliverySessionId differs from job'
        mtarget = manifest.get('target') if isinstance(manifest.get('target'), dict) else {}
        target = job.get('target') if isinstance(job.get('target'), dict) else {}
        for field in ('endpointId', 'browserEpoch', 'tabId', 'chatType', 'conversationId', 'projectId'):
            if mtarget.get(field) != target.get(field):
                return f'manifest target.{field} differs from job target'
        if str(manifest.get('message') or '') != str(job.get('message') or ''):
            return 'manifest message differs from job'
        ma = manifest.get('attachments')
        aa = job.get('attachments')
        if not isinstance(ma, list) or not isinstance(aa, list) or len(ma) != len(aa):
            return 'manifest attachments differ from job attachments'
        by_id = {str(x.get('attachmentId') or ''): x for x in aa if isinstance(x, dict)}
        if len(by_id) != len(aa):
            return 'job attachments have invalid or duplicate ids'
        for ordinal, item in enumerate(ma, start=1):
            if not isinstance(item, dict):
                return 'manifest attachment is not an object'
            if item.get('ordinal') != ordinal:
                return 'manifest attachment ordinal is invalid'
            current = aa[ordinal - 1]
            if not isinstance(current, dict):
                return 'job attachment is not an object'
            if str(item.get('attachmentId') or '') != str(current.get('attachmentId') or ''):
                return 'manifest attachment order differs from job'
            if item.get('outgoingFilename') != current.get('name'):
                return 'manifest attachment outgoingFilename differs from job'
            for field in ('size', 'mimeType'):
                if item.get(field) != current.get(field):
                    return f'manifest attachment {field} differs from job'
            current_artifact_id = current.get('artifactId')
            if current_artifact_id is not None:
                current_artifact_id = str(current_artifact_id).strip() or None
            if item.get('artifactId') != current_artifact_id:
                return 'manifest attachment artifactId differs from job'
            current_source_ids = current.get('sourceArtifactIds')
            if isinstance(current_source_ids, list):
                current_source_ids = [str(x).strip() for x in current_source_ids if str(x).strip()]
            else:
                current_source_ids = []
            if item.get('sourceArtifactIds') != current_source_ids:
                return 'manifest attachment sourceArtifactIds differ from job'
            path = Path(str(current.get('path') or '')).resolve()
            if not path.is_file():
                return 'manifest attachment file is missing'
            manifest_size = item.get('size')
            if (isinstance(manifest_size, bool) or not isinstance(manifest_size, int)
                    or manifest_size < 0):
                return 'manifest attachment size is invalid'
            if path.stat().st_size != manifest_size:
                return 'manifest attachment file size changed'
            if self._file_sha256(path) != str(item.get('sha256') or ''):
                return 'manifest attachment file bytes changed'
        return ''

    def _require_manifest(self, job: dict[str, Any]) -> None:
        error = self._manifest_error(job)
        if error:
            raise DeliveryError(f'DELIVERY_MANIFEST_INVALID: {error}')

    def get_job(self, run_id: str, job_id: str) -> dict[str, Any]:
        path = self.job_path(run_id, job_id)
        if not path.is_file():
            raise DeliveryError('delivery job not found')
        body = self._load_json(path, {})
        if not isinstance(body, dict):
            raise DeliveryError('bad delivery job')
        return body

    def save_job(self, job: dict[str, Any]) -> dict[str, Any]:
        run_id = str(job.get('runId') or '')
        job_id = str(job.get('jobId') or '')
        self._require_manifest(job)
        job['updatedAt'] = utc_now()
        self._derive_job_status(job)
        atomic_write_json(self.job_path(run_id, job_id), job)
        return job

    def list_jobs(self, run_id: str) -> list[dict[str, Any]]:
        root = self.delivery_root(run_id)
        if not root.is_dir():
            return []
        rows: list[dict[str, Any]] = []
        for path in root.iterdir():
            if not path.is_dir() or not (path / 'job.json').is_file():
                continue
            body = self._load_json(path / 'job.json', {})
            if isinstance(body, dict):
                rows.append(body)
        rows.sort(key=lambda x: str(x.get('createdAt') or ''), reverse=True)
        return rows

    def latest_job(self, run_id: str) -> dict[str, Any] | None:
        jobs = self.list_jobs(run_id)
        return jobs[0] if jobs else None

    def _collect_report_state(self, plan: dict[str, Any], state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        artifacts_by_path: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        seen_missing: set[str] = set()
        for step in plan.get('steps', []):
            if step.get('type') != 'COMMAND_GET_REPORTS':
                continue
            st = state.get('steps', {}).get(step.get('stepId'), {})
            for artifact in st.get('reportArtifacts') or []:
                if not isinstance(artifact, dict) or not artifact.get('present'):
                    continue
                key = str(artifact.get('originalPath') or artifact.get('snapshotPath') or artifact.get('name') or '')
                if key:
                    artifacts_by_path[key] = artifact
            candidates = list(st.get('missingReports') or [])
            # If the report step has never run, do not pretend files are missing yet.
            if st.get('status') not in {'DONE', 'DONE_WITH_WARNINGS', 'ERROR'}:
                candidates = []
            for item in candidates:
                value = str(item)
                if value not in seen_missing:
                    seen_missing.add(value)
                    missing.append(value)
        return list(artifacts_by_path.values()), missing

    def report_summary(self, plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        artifacts, missing = self._collect_report_state(plan, state)
        pending = []
        for step in plan.get('steps', []):
            if step.get('type') != 'COMMAND_GET_REPORTS':
                continue
            st = state.get('steps', {}).get(step.get('stepId'), {})
            if st.get('status') not in {'DONE', 'DONE_WITH_WARNINGS', 'ERROR'}:
                pending.append(step.get('stepId'))
        return {
            'artifacts': artifacts,
            'missing': missing,
            'pendingReportSteps': pending,
        }

    def _copy_raw(self, source: Path, destination_dir: Path, preferred_name: str) -> Path:
        destination = unique_path(destination_dir, preferred_name)
        shutil.copy2(source, destination)
        return destination

    def _zip_one(self, source: Path, destination_dir: Path, preferred_name: str) -> Path:
        archive_name = safe_name(preferred_name) + '.zip'
        destination = unique_path(destination_dir, archive_name)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(source, arcname=safe_name(preferred_name))
        return destination

    @staticmethod
    def _unique_archive_member_name(preferred_name: str, used_names: set[str]) -> str:
        candidate = safe_name(preferred_name)
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
        path = Path(candidate)
        stem = path.stem or 'file'
        suffix = path.suffix
        for idx in range(2, 10000):
            item = f'{stem}-{idx}{suffix}'
            if item not in used_names:
                used_names.add(item)
                return item
        raise DeliveryError('cannot allocate unique archive member filename')

    def _write_smart_zip_candidate(
        self,
        items: list[dict[str, Any]],
        destination: Path,
    ) -> list[dict[str, Any]]:
        used_names: set[str] = set()
        members: list[dict[str, Any]] = []
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for item in items:
                source = Path(str(item['sourcePath']))
                arcname = self._unique_archive_member_name(str(item['preferredName']), used_names)
                zf.write(source, arcname=arcname)
                members.append({
                    'name': arcname,
                    'kind': item.get('kind'),
                    'artifactId': item.get('artifactId'),
                    'originalPath': item.get('originalPath'),
                    'sourceSize': source.stat().st_size,
                })
        return members

    def _materialize_terminal(self, run_id: str, files_dir: Path) -> tuple[Path, str]:
        text = self.terminal_log_builder(run_id)
        name = f'pap2-terminal-{run_id}.log'
        path = unique_path(files_dir, name)
        path.write_text(text, encoding='utf-8')
        return path, name

    def create_job(
        self,
        run_id: str,
        result: dict[str, Any],
        plan: dict[str, Any],
        state: dict[str, Any],
        message: str,
        mode: str,
        aggregate_max_bytes: int,
        stall_timeout_seconds: int,
        *,
        delivery_session_id: str | None = None,
        logical_delivery_id: str | None = None,
        side_effect_key: str | None = None,
    ) -> dict[str, Any]:
        mode = str(mode or 'open')
        if mode not in {'smart_zip', 'open', 'packed', 'single_archive'}:
            raise DeliveryError('unsupported delivery mode')
        aggregate_max_bytes = max(1024 * 1024, int(aggregate_max_bytes or SMART_ZIP_MAX_BYTES))
        if mode == 'smart_zip':
            aggregate_max_bytes = min(aggregate_max_bytes, SMART_ZIP_MAX_BYTES)
        stall_timeout_seconds = max(30, int(stall_timeout_seconds or 120))

        pap_source = result.get('papSource') if isinstance(result.get('papSource'), dict) else {}
        target_tab_id = pap_source.get('tabId')
        target_url = str(pap_source.get('url') or result.get('page') or '')
        target_chat_type = str(result.get('chatType') or pap_source.get('chatType') or 'unknown')
        target_chat_label = str(result.get('chatLabel') or pap_source.get('chatLabel') or target_chat_type or 'Unknown')
        target_endpoint_id = str(pap_source.get('endpointId') or '').strip()
        target_browser_epoch = str(pap_source.get('browserEpoch') or '').strip()
        target_conversation_id = str(pap_source.get('conversationId') or '').strip()
        target_project_id = pap_source.get('projectId')
        if not target_endpoint_id:
            raise DeliveryError('Run delivery target has no endpointId')
        if not target_browser_epoch:
            raise DeliveryError('Run delivery target has no browserEpoch')
        if not target_conversation_id:
            raise DeliveryError('Run delivery target has no conversationId')
        logical_delivery_id, side_effect_key = self._logical_identity(
            run_id, side_effect_key, logical_delivery_id)
        if target_tab_id in (None, ''):
            raise DeliveryError('Run has no papSource.tabId. Update the browser extension and create a new run.')
        try:
            target_tab_id = int(target_tab_id)
        except Exception as exc:
            raise DeliveryError('invalid papSource.tabId') from exc

        report_summary = self.report_summary(plan, state)
        pending_report_steps = report_summary['pendingReportSteps']
        if pending_report_steps:
            raise DeliveryError('COMMAND_GET_REPORTS not executed yet: ' + ', '.join(str(x) for x in pending_report_steps))

        artifacts = report_summary['artifacts']
        missing = report_summary['missing']
        base_message = str(message or '')

        job_id = f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")}_{uuid.uuid4().hex[:8]}'
        job_dir = self.job_dir(run_id, job_id)
        files_dir = job_dir / 'files'
        files_dir.mkdir(parents=True, exist_ok=False)

        source_items: list[dict[str, Any]] = []
        terminal_path, terminal_name = self._materialize_terminal(run_id, files_dir)
        source_items.append({
            'kind': 'terminal_log',
            'artifactId': None,
            'originalPath': str(self.run_dir(run_id) / 'executor' / 'run-full.log'),
            'sourcePath': str(terminal_path),
            'preferredName': terminal_name,
            'alreadyMaterialized': True,
            'isArchive': False,
        })
        for artifact in artifacts:
            source_path = Path(str(artifact.get('snapshotPath') or '')).resolve()
            if not source_path.is_file():
                original = str(artifact.get('originalPath') or artifact.get('name') or '')
                if original and original not in missing:
                    missing.append(original)
                continue
            preferred = safe_name(Path(str(artifact.get('originalPath') or artifact.get('name') or source_path.name)).name)
            source_items.append({
                'kind': 'report',
                'artifactId': artifact.get('artifactId'),
                'originalPath': artifact.get('originalPath'),
                'sourcePath': str(source_path),
                'preferredName': preferred,
                'alreadyMaterialized': False,
                'isArchive': is_archive_name(preferred),
            })

        final_message = with_missing_suffix(base_message, missing)

        attachments: list[dict[str, Any]] = []

        def add_attachment(
            path: Path,
            kind: str,
            source_desc: str | None = None,
            display_name: str | None = None,
            *,
            artifact_id: str | None = None,
            source_artifact_ids: list[str] | None = None,
            extra: dict[str, Any] | None = None,
        ) -> None:
            attachment_id = f'a{len(attachments)+1:03d}'
            size = path.stat().st_size
            visible_name = safe_name(display_name or path.name)
            mime = mimetypes.guess_type(visible_name)[0] or 'application/octet-stream'
            record = {
                'attachmentId': attachment_id,
                'name': visible_name,
                'path': str(path),
                'size': size,
                'mimeType': mime,
                'kind': kind,
                'source': source_desc,
                'artifactId': str(artifact_id).strip() if artifact_id else None,
                'sourceArtifactIds': [str(x).strip() for x in (source_artifact_ids or []) if str(x).strip()],
                'state': 'PENDING',
                'attempts': 0,
                'bytesFetched': 0,
                'totalBytes': size,
                'error': None,
                'phase': 'WAITING',
                'createdAt': utc_now(),
                'updatedAt': utc_now(),
                'lastProgressAt': None,
            }
            if extra:
                record.update(extra)
            attachments.append(record)

        if mode == 'smart_zip':
            # Automatic delivery policy:
            # - existing archives are never nested;
            # - files >= max size are sent raw;
            # - two or more remaining ordinary files are grouped into ZIP parts;
            # - every produced ZIP is measured and recursively split until it is <= max size.
            separate_items: list[dict[str, Any]] = []
            packable_items: list[dict[str, Any]] = []
            for item in source_items:
                source_size = Path(str(item['sourcePath'])).stat().st_size
                if item.get('isArchive') or source_size >= aggregate_max_bytes:
                    separate_items.append(item)
                else:
                    packable_items.append(item)

            if len(packable_items) <= 1:
                for item in packable_items:
                    src = Path(str(item['sourcePath']))
                    if item.get('alreadyMaterialized'):
                        dest = src
                    else:
                        dest = self._copy_raw(src, files_dir, str(item['preferredName']))
                    add_attachment(
                        dest,
                        'terminal_log' if item.get('kind') == 'terminal_log' else 'report',
                        str(item.get('originalPath') or ''),
                        str(item['preferredName']),
                        artifact_id=item.get('artifactId'),
                    )
            else:
                part_counter = 0

                def emit_group(group: list[dict[str, Any]]) -> None:
                    nonlocal part_counter
                    if not group:
                        return
                    candidate = files_dir / f'.pap2-smart-zip-{uuid.uuid4().hex}.tmp.zip'
                    members = self._write_smart_zip_candidate(group, candidate)
                    size = candidate.stat().st_size
                    if size <= aggregate_max_bytes:
                        part_counter += 1
                        final_name = f'pap2-files-{run_id}-part{part_counter:02d}.zip'
                        destination = unique_path(files_dir, final_name)
                        os.replace(candidate, destination)
                        add_attachment(
                            destination,
                            'smart_bundle',
                            'automatically grouped non-archive delivery files',
                            destination.name,
                            source_artifact_ids=[
                                str(item.get('artifactId')) for item in group if item.get('artifactId')
                            ],
                            extra={'members': members},
                        )
                        return

                    candidate.unlink(missing_ok=True)
                    if len(group) == 1:
                        # Extremely rare case: DEFLATE overhead made a sub-limit
                        # source exceed the hard ZIP limit. Send the original raw.
                        item = group[0]
                        src = Path(str(item['sourcePath']))
                        dest = src if item.get('alreadyMaterialized') else self._copy_raw(src, files_dir, str(item['preferredName']))
                        add_attachment(
                            dest,
                            'smart_separate',
                            str(item.get('originalPath') or ''),
                            str(item['preferredName']),
                            artifact_id=item.get('artifactId'),
                            extra={'separateReason': 'ZIP_EXCEEDS_LIMIT'},
                        )
                        return

                    split = max(1, len(group) // 2)
                    emit_group(group[:split])
                    emit_group(group[split:])

                # Start with the whole packable set and split only after measuring
                # the actual compressed ZIP. This follows the user-facing rule:
                # split when the resulting archive exceeds the limit, not merely
                # because the uncompressed source sum is large.
                emit_group(packable_items)

                # terminal_path is only an intermediate source when it was packed.
                # Keep it if an edge-case fallback attached the raw terminal.
                terminal_is_attachment = any(
                    Path(str(attachment.get('path') or '')).resolve() == terminal_path.resolve()
                    for attachment in attachments
                )
                if any(item.get('kind') == 'terminal_log' for item in packable_items) and not terminal_is_attachment:
                    terminal_path.unlink(missing_ok=True)

            for item in separate_items:
                src = Path(str(item['sourcePath']))
                if item.get('alreadyMaterialized'):
                    dest = src
                else:
                    dest = self._copy_raw(src, files_dir, str(item['preferredName']))
                source_size = dest.stat().st_size
                reason = 'ALREADY_ARCHIVED' if item.get('isArchive') else 'LARGE_FILE'
                add_attachment(
                    dest,
                    'report_archive' if item.get('isArchive') else ('terminal_log_large' if item.get('kind') == 'terminal_log' else 'report_large'),
                    str(item.get('originalPath') or ''),
                    str(item['preferredName']),
                    artifact_id=item.get('artifactId'),
                    extra={'separateReason': reason, 'sourceSize': source_size},
                )

        elif mode == 'open':
            # terminal_path already lives in files_dir; other sources are copied with original names.
            add_attachment(terminal_path, 'terminal_log', 'terminal log', terminal_name)
            for item in source_items[1:]:
                src = Path(item['sourcePath'])
                dest = self._copy_raw(src, files_dir, item['preferredName'])
                add_attachment(
                    dest,
                    'report_archive' if item['isArchive'] else 'report',
                    str(item.get('originalPath') or ''),
                    item['preferredName'],
                    artifact_id=item.get('artifactId'),
                )

        elif mode == 'packed':
            # Compress each non-archive item separately. Existing archives stay untouched.
            terminal_zip = self._zip_one(terminal_path, files_dir, terminal_name)
            add_attachment(terminal_zip, 'terminal_log_packed', 'terminal log', terminal_name + '.zip')
            for item in source_items[1:]:
                src = Path(item['sourcePath'])
                if item['isArchive']:
                    dest = self._copy_raw(src, files_dir, item['preferredName'])
                    add_attachment(
                        dest,
                        'report_archive',
                        str(item.get('originalPath') or ''),
                        item['preferredName'],
                        artifact_id=item.get('artifactId'),
                    )
                else:
                    dest = self._zip_one(src, files_dir, item['preferredName'])
                    add_attachment(
                        dest,
                        'report_packed',
                        str(item.get('originalPath') or ''),
                        item['preferredName'] + '.zip',
                        artifact_id=item.get('artifactId'),
                    )

        else:  # single_archive
            # Do not nest already archived reports. They are attached as-is beside one archive containing terminal + non-archives.
            aggregate = unique_path(files_dir, f'pap2-reports-{run_id}.tar.gz')
            with tarfile.open(aggregate, 'w:gz') as tf:
                tf.add(terminal_path, arcname=terminal_name)
                used_names: set[str] = {terminal_name}
                for item in source_items[1:]:
                    if item['isArchive']:
                        continue
                    src = Path(item['sourcePath'])
                    arcname = safe_name(item['preferredName'])
                    base = arcname
                    n = 2
                    while arcname in used_names:
                        p = Path(base)
                        arcname = f'{p.stem}-{n}{p.suffix}'
                        n += 1
                    used_names.add(arcname)
                    tf.add(src, arcname=arcname)
            archive_size = aggregate.stat().st_size
            if archive_size > aggregate_max_bytes:
                aggregate.unlink(missing_ok=True)
                shutil.rmtree(job_dir, ignore_errors=True)
                raise DeliveryError(
                    f'aggregate archive too large: {archive_size} bytes > {aggregate_max_bytes} bytes; choose open/packed or raise limit'
                )
            add_attachment(
                aggregate, 'aggregate_archive', 'terminal log + non-archive reports',
                f'pap2-reports-{run_id}.tar.gz',
                source_artifact_ids=[
                    str(item.get('artifactId')) for item in source_items[1:]
                    if not item.get('isArchive') and item.get('artifactId')
                ],
            )
            for item in source_items[1:]:
                if not item['isArchive']:
                    continue
                src = Path(item['sourcePath'])
                dest = self._copy_raw(src, files_dir, item['preferredName'])
                add_attachment(
                    dest,
                    'report_archive',
                    str(item.get('originalPath') or ''),
                    item['preferredName'],
                    artifact_id=item.get('artifactId'),
                )

        created = utc_now()
        job = {
            'schemaVersion': 1,
            'jobId': job_id,
            'runId': run_id,
            'createdAt': created,
            'updatedAt': created,
            'status': 'QUEUED',
            'dispatchEpoch': self.dispatch_epoch,
            'mode': mode,
            'aggregateMaxBytes': aggregate_max_bytes,
            'packagingPolicy': {
                'type': 'smart_zip_v2' if mode == 'smart_zip' else mode,
                'maxArchiveBytes': aggregate_max_bytes if mode == 'smart_zip' else None,
                'largeFileThresholdBytes': aggregate_max_bytes if mode == 'smart_zip' else None,
                'existingArchivesSeparate': mode == 'smart_zip',
                'splitBasis': 'actual_zip_size' if mode == 'smart_zip' else None,
            },
            'stallTimeoutSeconds': stall_timeout_seconds,
            'target': {
                'endpointId': target_endpoint_id,
                'browserEpoch': target_browser_epoch,
                'tabId': target_tab_id,
                'url': target_url,
                'chatType': target_chat_type,
                'conversationId': target_conversation_id,
                'projectId': target_project_id,
                'chatLabel': target_chat_label,
            },
            'logicalDeliveryId': logical_delivery_id,
            'sideEffectKey': side_effect_key,
            'deliverySessionId': delivery_session_id,
            'message': final_message,
            'messageState': 'PENDING',
            'messageError': None,
            'messageInsertedAt': None,
            'conversationBaseline': None,
            'consumedAt': None,
            'consumedReason': None,
            'sendState': 'NOT_REQUESTED',
            'sendError': None,
            'claimedBy': None,
            'claimLeaseToken': None,
            'claimHeartbeatAt': None,
            'claimExpiresAt': None,
            'claimLeaseSeconds': CLAIM_LEASE_SECONDS,
            'attachments': attachments,
            'missingReports': missing,
            'reportCount': len(artifacts),
        }
        job['deliveryManifest'] = self._build_delivery_manifest(
            delivery_id=job_id,
            logical_delivery_id=logical_delivery_id,
            side_effect_key=side_effect_key,
            delivery_session_id=delivery_session_id,
            target=job['target'],
            message=final_message,
            attachments=attachments,
        )
        job['deliveryManifestSha256'] = self._manifest_digest(job['deliveryManifest'])
        saved = self.save_job(job)
        saved['supersededOlderJobs'] = self.supersede_older_jobs_for_tab(target_tab_id, run_id, job_id)
        return self.save_job(saved)

    @staticmethod
    def _same_page_url(left: str, right: str) -> bool:
        return str(left or '').split('#', 1)[0] == str(right or '').split('#', 1)[0]

    REPLAY_FOUND = 'FOUND'
    REPLAY_ABSENT = 'ABSENT'
    REPLAY_UNPROVABLE = 'UNPROVABLE'

    def _existing_recovery_replay(
        self,
        source_run_id: str,
        source_job_id: str,
        tab_id: int,
        page_url: str,
    ) -> tuple[str, dict[str, Any] | None, str]:
        """The replay already made for this source, or a stated reason there is none.

        Three answers rather than a job or `None`. The single `None` meant both
        "no replay exists" and "a replay exists whose identity I cannot read",
        and the caller acted on the second as though it were the first: it wrote
        a second delivery and marked the first `SUPERSEDED`. A terminal mutation
        decided by a hole in the evidence is the thing this block exists to
        remove.

        The writer stamps every replay with `recoveryReplay: True` and a
        `recoveryOf` object in the same write. An ordinary delivery carries
        neither. A half-present or non-canonical pair is therefore persisted
        contradiction, never proof that the replay is absent.
        """
        if not self.data_dir.is_dir():
            return self.REPLAY_ABSENT, None, ''

        for run_dir in self.data_dir.iterdir():
            if not run_dir.is_dir():
                continue
            delivery_root = run_dir / 'executor' / 'delivery'
            if not delivery_root.is_dir():
                continue

            for path in delivery_root.iterdir():
                job_file = path / 'job.json'
                if not job_file.is_file():
                    continue
                try:
                    job = json.loads(job_file.read_text('utf-8'))
                except Exception as exc:
                    return (self.REPLAY_UNPROVABLE, None,
                            f'unreadable delivery job {job_file}: {exc}')
                if not isinstance(job, dict) or not job.get('jobId'):
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{job_file} is not a delivery job')

                # Writer contract: ordinary deliveries carry neither field;
                # recovery replays carry both, in the same persisted write.
                # A half-present or non-canonical marker is contradictory
                # evidence, not proof that the row is an ordinary delivery.
                has_replay_marker = 'recoveryReplay' in job
                has_recovery_of = 'recoveryOf' in job
                if not has_replay_marker and not has_recovery_of:
                    continue

                where = f"run={job.get('runId')} job={job.get('jobId')}"
                replay_marker = job.get('recoveryReplay')
                if replay_marker is not True:
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: recoveryReplay must be exactly true when '
                            f'recovery metadata is present: {replay_marker!r}')

                recovery_of = job.get('recoveryOf')
                if not isinstance(recovery_of, dict):
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: recoveryOf is not an object: {recovery_of!r}')
                replay_run = recovery_of.get('runId')
                replay_job = recovery_of.get('jobId')
                if not isinstance(replay_run, str) or not replay_run:
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: recoveryOf.runId is not a non-empty string: '
                            f'{replay_run!r}')
                if not isinstance(replay_job, str) or not replay_job:
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: recoveryOf.jobId is not a non-empty string: '
                            f'{replay_job!r}')
                same_source = (
                    replay_run == str(source_run_id)
                    and replay_job == str(source_job_id)
                )

                # A replay-like row must be a canonical writer row before it may
                # be skipped for naming another source. Otherwise a damaged
                # foreign replay would disappear from the proof simply because
                # recoveryOf happened to differ first. Validate the page field
                # explicitly before classify_target: that shared classifier may
                # prove OTHER from tabId alone and then intentionally stop before
                # reading url, while the replay writer contract requires both
                # stored coordinates themselves to be usable.
                raw_target = job.get('target')
                if isinstance(raw_target, dict):
                    if 'url' not in raw_target:
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: target has no url')
                    if not isinstance(raw_target.get('url'), str):
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: target url is not a string: '
                                f'{raw_target.get("url")!r}')

                verdict, why = self.classify_target(
                    job, tab_id=tab_id, page_url=page_url)
                if verdict == self.TARGET_UNPROVABLE:
                    return self.REPLAY_UNPROVABLE, None, f'{where}: {why}'

                status = job.get('status')
                if not isinstance(status, str) or status not in KNOWN_JOB_STATES:
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: replay status is not a canonical delivery '
                            f'state: {status!r}')

                dispatch_epoch = job.get('dispatchEpoch')
                if status == PAUSED_JOB_STATE:
                    # pause_unfinished_jobs_after_restart is the writer of the
                    # paused form and deliberately clears dispatchEpoch.  The
                    # replay still exists; a restart is not permission to clone
                    # it again.
                    if dispatch_epoch is not None:
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: paused replay carries dispatchEpoch: '
                                f'{dispatch_epoch!r}')
                elif status in {'SUPERSEDED', 'CANCELLED'} and dispatch_epoch is None:
                    # A terminal replay can be produced from the paused writer
                    # form without ever being resumed. Prepare retires an
                    # unleased PAUSED_AFTER_RESTART job in-place, so
                    # SUPERSEDED legitimately retains dispatchEpoch=None.  Null
                    # is therefore canonical only when the persisted pause
                    # provenance proves that route; accepting a bare null on a
                    # terminal row would turn the review-25 corruption back
                    # into a legal lifecycle.
                    paused_at = job.get('pausedAt')
                    paused_from_epoch = job.get('pausedFromDispatchEpoch')
                    if (
                        job.get('pauseReason') != 'BACKEND_RESTART'
                        or decision_dt(paused_at) is None
                        or 'pausedFromDispatchEpoch' not in job
                        or (
                            paused_from_epoch is not None
                            and (
                                not isinstance(paused_from_epoch, str)
                                or not paused_from_epoch
                            )
                        )
                    ):
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: terminal replay has null dispatchEpoch '
                                f'without canonical restart-pause provenance')
                else:
                    if not isinstance(dispatch_epoch, str) or not dispatch_epoch:
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: replay dispatchEpoch is not a non-empty '
                                f'string: {dispatch_epoch!r}')

                    if status not in TERMINAL_JOB_STATES and dispatch_epoch != self.dispatch_epoch:
                        # A non-terminal job from another epoch is supposed to
                        # have been rewritten to PAUSED_AFTER_RESTART before
                        # requests are served. Seeing the old live form here is
                        # contradictory persisted state, not evidence that no
                        # replay exists.
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: non-terminal replay belongs to dispatchEpoch '
                                f'{dispatch_epoch!r}, current is {self.dispatch_epoch!r}')

                if not same_source:
                    # Only after the whole persisted writer row is usable may a
                    # different recoveryOf become a proven identity skip.
                    continue

                if verdict == self.TARGET_OTHER:
                    # recoveryOf already proves that this row claims to replay
                    # this exact source. The writer derives its tab/page from
                    # that source, so a different address is contradictory
                    # persisted evidence, not a legitimate replay elsewhere.
                    return (self.REPLAY_UNPROVABLE, None,
                            f'{where}: replay target contradicts its source: {why}')

                if status in {'SUPERSEDED', 'CANCELLED'}:
                    # Retiring a replay is not proof that its delivery happened.
                    # create_job can supersede a QUEUED/PENDING replay before it
                    # was ever inserted or sent, and returning that terminal row
                    # as FOUND makes recovery impossible forever.  Conversely,
                    # absence must be proved too: a malformed sendState cannot be
                    # interpreted as "not sent" and used to manufacture another
                    # replay.
                    send_state = job.get('sendState')
                    canonical_send_states = {
                        'NOT_REQUESTED', 'SEND_REQUESTED', 'SEND_ERROR',
                        'SENT', 'MANUAL_SENT',
                    }
                    if not isinstance(send_state, str) or send_state not in canonical_send_states:
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: terminal replay sendState is not '
                                f'canonical: {send_state!r}')
                    if send_state == 'SEND_REQUESTED':
                        # A click was requested but no outcome was persisted.
                        # That is neither a delivered replay nor proof that no
                        # delivery happened, so it cannot be turned into ABSENT.
                        return (self.REPLAY_UNPROVABLE, None,
                                f'{where}: retired replay has an unresolved '
                                f'SEND_REQUESTED outcome')
                    if send_state in {'NOT_REQUESTED', 'SEND_ERROR'}:
                        # This replay exists as history, but not as the delivered
                        # result whose idempotence the helper is answering. Keep
                        # scanning in case a later canonical replay for the same
                        # source exists; if none does, the answer is ABSENT and a
                        # fresh replay may be created.
                        continue

                # SENT/CONSUMED prove delivery by status. SUPERSEDED/CANCELLED
                # reach here only when sendState independently proves submission.
                # Paused/non-terminal rows still represent an outstanding replay
                # and remain FOUND for idempotence.
                return self.REPLAY_FOUND, job, ''

        return self.REPLAY_ABSENT, None, ''

    @staticmethod
    def _job_submitted_at(job: dict[str, Any]) -> tuple[datetime | None, str]:
        """When this delivery was submitted, or why that cannot be established.

        The first field that carries a value answers, and if that value is not
        a usable timestamp the answer is a refusal rather than the next field
        down: falling through would let a damaged `consumedAt` be silently
        replaced by `createdAt` and change which delivery is called the latest.

        Returned rather than raised because the callers differ: one refuses the
        whole lookup, the other prefers the source it can prove.
        """
        for field in ('consumedAt', 'sentAt', 'updatedAt', 'createdAt'):
            raw = job.get(field)
            if raw in (None, ''):
                continue
            parsed = decision_dt(raw)
            if parsed is None:
                return None, f'{field} is not a timezone-aware timestamp: {raw!r}'
            return parsed, ''
        return None, ''

    def find_latest_submitted_job(
        self,
        *,
        tab_id: int,
        page_url: str,
        max_age_seconds: int = 2 * 60 * 60,
    ) -> tuple[str, dict[str, Any] | None, str]:
        """The newest submitted delivery for this tab/page, as one of three answers.

        `(SUBMITTED_FOUND, job, "")`, `(SUBMITTED_ABSENT, None, "")` or
        `(SUBMITTED_UNPROVABLE, None, reason)`.

        Two answers used to be one. Returning `None` for "there is nothing" and
        for "there is something and I cannot tell which is newest" let the
        caller read the second as the first and fall back to an explicitly named
        older source — UNKNOWN turned into absence, and a recovery replay was
        built from a delivery that had been superseded.

        Unprovable has two shapes here, and they are the two already settled for
        Prepare order: a submitted time that is missing an offset or unreadable,
        and two candidates sharing the newest instant, which is provable time
        that still establishes no order.
        """
        candidates: list[tuple[datetime, dict[str, Any]]] = []

        if not self.data_dir.is_dir():
            return self.SUBMITTED_ABSENT, None, ''

        current = utc_now_dt()

        for run_dir in self.data_dir.iterdir():
            if not run_dir.is_dir():
                continue

            delivery_root = run_dir / 'executor' / 'delivery'
            if not delivery_root.is_dir():
                continue

            for path in delivery_root.iterdir():
                job_file = path / 'job.json'
                if not job_file.is_file():
                    continue

                # Read failures are evidence, not empty space. This used to go
                # through the tolerant loader, which answers `{}` for anything
                # it cannot parse; the empty target then matched no tab and the
                # damaged job disappeared from the reckoning. It may be the
                # newer delivery for this very tab, so nothing here can be
                # called the latest while it cannot be read.
                try:
                    job = json.loads(job_file.read_text('utf-8'))
                except Exception as exc:
                    return (self.SUBMITTED_UNPROVABLE, None,
                            f'unreadable delivery job {job_file}: {exc}')
                if not isinstance(job, dict) or not job.get('jobId'):
                    return (self.SUBMITTED_UNPROVABLE, None,
                            f'{job_file} is not a delivery job')

                verdict, why = self.classify_target(job, tab_id=tab_id, page_url=page_url)
                if verdict == self.TARGET_UNPROVABLE:
                    return (self.SUBMITTED_UNPROVABLE, None,
                            f"run={job.get('runId')} job={job.get('jobId')}: {why}")
                if verdict == self.TARGET_OTHER:
                    # Proven to belong elsewhere: a fact about the delivery,
                    # and the only reason a job leaves this scan on its address.
                    continue

                status = str(job.get('status') or '')
                send_state = str(job.get('sendState') or '')
                submitted = (
                    status in {'CONSUMED', 'SENT'}
                    or send_state in {'MANUAL_SENT', 'SENT'}
                )
                if not submitted:
                    continue

                where = f"run={job.get('runId')} job={job.get('jobId')}"
                submitted_at, unprovable = self._job_submitted_at(job)
                if unprovable:
                    # UNKNOWN, not absent. Skipping this job would name some
                    # other delivery the latest on evidence that has a hole in
                    # it, and comparing the value would raise a bare TypeError
                    # from inside recovery — which is what it used to do.
                    return self.SUBMITTED_UNPROVABLE, None, f'{where}: {unprovable}'
                if submitted_at is None:
                    # The status already proves this delivery was submitted, so
                    # it is not absent — what is missing is any evidence of
                    # when. Skipping it would let an older delivery be called
                    # the latest over a job that may well be newer.
                    return (self.SUBMITTED_UNPROVABLE, None,
                            f'{where}: submitted with no timestamp to place it in time')

                age = (current - submitted_at).total_seconds()
                if age < 0:
                    # Sent after the current moment: the stored time contradicts
                    # itself. Being out of the recovery window is a proven fact
                    # about a delivery, and this is not that — it is a time
                    # nobody can use, which is exactly the case the invariant
                    # calls UNKNOWN.
                    return (self.SUBMITTED_UNPROVABLE, None,
                            f'{where}: submitted time is in the future '
                            f'({submitted_at.isoformat()})')
                if age > max_age_seconds:
                    # Proven older than the recovery window: legitimately not a
                    # candidate, and the only skip left in this loop.
                    continue

                candidates.append((submitted_at, job))

        if not candidates:
            return self.SUBMITTED_ABSENT, None, ''

        candidates.sort(key=lambda row: row[0], reverse=True)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            # Equal timestamps are not an order. Taking the first of them would
            # make `Path.iterdir` decide which delivery a replay is built from,
            # exactly as it once decided which delivery was destroyed.
            return (self.SUBMITTED_UNPROVABLE, None,
                    f'two submitted deliveries share the newest instant '
                    f'({candidates[0][0].isoformat()})')
        return self.SUBMITTED_FOUND, candidates[0][1], ''

    def resolve_recovery_source(
        self,
        *,
        tab_id: int,
        page_url: str,
        source_run_id: str = '',
        source_job_id: str = '',
    ) -> tuple[dict[str, Any], str]:
        """Resolve the newest submitted source for the same tab/page.

        Browser-provided runId/jobId is only a hint because extension reloads
        can erase the tab-side reference. If a newer submitted job exists on
        disk for the same tab/page, the newer job wins.
        """
        explicit: dict[str, Any] | None = None

        if source_run_id and source_job_id:
            try:
                candidate = self.get_job(source_run_id, source_job_id)
                target = candidate.get('target') if isinstance(candidate.get('target'), dict) else {}
                status = str(candidate.get('status') or '')
                send_state = str(candidate.get('sendState') or '')
                submitted = (
                    status in {'CONSUMED', 'SENT'}
                    or send_state in {'MANUAL_SENT', 'SENT'}
                )
                verdict, why = self.classify_target(candidate, tab_id=tab_id, page_url=page_url)
                if verdict == self.TARGET_UNPROVABLE:
                    # The same decision as the scan takes, so it needs the same
                    # rule: a source whose address cannot be read is not quietly
                    # dropped in favour of whatever else is lying around.
                    raise DeliveryError(
                        f'RECOVERY_SOURCE_UNPROVABLE: the named source has an '
                        f'unreadable target: {why}')
                if submitted and verdict == self.TARGET_MATCH:
                    explicit = candidate
            except DeliveryError as exc:
                if 'RECOVERY_SOURCE_UNPROVABLE' in str(exc):
                    raise
                explicit = None

        state, latest, reason = self.find_latest_submitted_job(
            tab_id=tab_id,
            page_url=page_url,
        )

        if state == self.SUBMITTED_UNPROVABLE:
            # The newest submitted delivery cannot be established. Falling
            # back to the source the browser named would build a replay from a
            # delivery that may well have been superseded by the one that
            # cannot be read — a guess wearing the clothes of a reference.
            raise DeliveryError(
                f'RECOVERY_SOURCE_UNPROVABLE: cannot establish the latest '
                f'submitted delivery for this chat tab/page: {reason}')

        if explicit is None and latest is None:
            raise DeliveryError(
                'no submitted PAP delivery found for this chat tab/page'
            )

        if explicit is None:
            return latest, 'LATEST_SUBMITTED_SAME_TAB_PAGE'

        explicit_at, explicit_bad = self._job_submitted_at(explicit)
        if explicit_bad:
            # The named source carries a time nobody can compare. It is not
            # preferred by default just because it was named.
            raise DeliveryError(
                f'RECOVERY_SOURCE_UNPROVABLE: the named source has no usable '
                f'submitted time: {explicit_bad}')

        if latest is None:
            return explicit, 'BROWSER_SOURCE_REFERENCE'

        latest_at, _latest_bad = self._job_submitted_at(latest)

        if latest_at and (not explicit_at or latest_at > explicit_at):
            return latest, 'LATEST_SUBMITTED_SAME_TAB_PAGE'

        return explicit, 'BROWSER_SOURCE_REFERENCE'

    def create_recovery_replay(
        self,
        *,
        tab_id: int,
        page_url: str,
        source_run_id: str = '',
        source_job_id: str = '',
        failure_key: str = '',
        failure_row_index: str = '',
        reason: str = '',
    ) -> dict[str, Any]:
        """Clone the exact terminal PAP delivery into a fresh draft-replay job.

        This never mutates/reactivates the terminal source job. A fresh job is
        important because CONSUMED/SENT are deliberately non-pollable and must
        stay immutable for one-shot delivery semantics.
        """
        with self.lock:
            source, source_resolution = self.resolve_recovery_source(
                tab_id=tab_id,
                page_url=page_url,
                source_run_id=source_run_id,
                source_job_id=source_job_id,
            )
            source_run_id = str(source.get('runId') or '')
            source_job_id = str(source.get('jobId') or '')

            source_status = str(source.get('status') or '')
            source_send = str(source.get('sendState') or '')
            if source_status not in {'CONSUMED', 'SENT'} and source_send not in {'MANUAL_SENT', 'SENT'}:
                raise DeliveryError('recovery source job was not submitted')

            target = source.get('target') if isinstance(source.get('target'), dict) else {}
            if int(target.get('tabId') or -1) != int(tab_id):
                raise DeliveryError('recovery source belongs to another tab')

            target_url = str(target.get('url') or '')
            if target_url and page_url and not self._same_page_url(target_url, page_url):
                raise DeliveryError('recovery source belongs to another chat page')

            # The same rule as everywhere else, through the same helper. This
            # was a second, weaker copy of it: it accepted a naive stored value
            # and then subtracted it from an aware one.
            submitted_at, unprovable = self._job_submitted_at(source)
            if unprovable:
                raise DeliveryError(
                    f'RECOVERY_SOURCE_UNPROVABLE: the source has no usable '
                    f'submitted time: {unprovable}')
            if submitted_at is not None:
                age_seconds = (utc_now_dt() - submitted_at).total_seconds()
                if age_seconds > 2 * 60 * 60:
                    raise DeliveryError('recovery source is older than 2 hours')

            state, existing, why = self._existing_recovery_replay(
                source_run_id,
                source_job_id,
                tab_id,
                page_url,
            )
            if state == self.REPLAY_UNPROVABLE:
                # Before `new_job_dir`, before any write. Whether a replay for
                # this source already exists cannot be established, so creating
                # a second one would be a guess with a delivery at the end of
                # it — and retiring the first would bury the evidence.
                raise DeliveryError(
                    f'RECOVERY_REPLAY_UNPROVABLE: cannot establish whether a '
                    f'recovery replay already exists for this delivery: {why}')
            if existing is not None:
                return existing

            new_job_id = (
                f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")}_'
                f'recovery_{uuid.uuid4().hex[:8]}'
            )
            new_job_dir = self.job_dir(source_run_id, new_job_id)
            files_dir = new_job_dir / 'files'
            files_dir.mkdir(parents=True, exist_ok=False)

            source_files_root = (self.job_dir(source_run_id, source_job_id) / 'files').resolve()
            attachments: list[dict[str, Any]] = []

            try:
                for source_attachment in source.get('attachments') or []:
                    source_path = Path(str(source_attachment.get('path') or '')).resolve()
                    if source_files_root not in source_path.parents or not source_path.is_file():
                        raise DeliveryError(
                            f'recovery attachment file not found: '
                            f'{source_attachment.get("name") or source_attachment.get("attachmentId")}'
                        )

                    visible_name = safe_name(
                        str(source_attachment.get('name') or source_path.name)
                    )
                    destination = unique_path(files_dir, visible_name)
                    shutil.copy2(source_path, destination)

                    attachment_id = f'a{len(attachments)+1:03d}'
                    size = destination.stat().st_size
                    mime = str(
                        source_attachment.get('mimeType')
                        or mimetypes.guess_type(visible_name)[0]
                        or 'application/octet-stream'
                    )

                    attachments.append({
                        'attachmentId': attachment_id,
                        'name': visible_name,
                        'path': str(destination),
                        'size': size,
                        'mimeType': mime,
                        'kind': source_attachment.get('kind'),
                        'source': source_attachment.get('source'),
                        'artifactId': source_attachment.get('artifactId'),
                        'sourceArtifactIds': list(source_attachment.get('sourceArtifactIds') or []),
                        'state': 'PENDING',
                        'attempts': 0,
                        'bytesFetched': 0,
                        'totalBytes': size,
                        'error': None,
                        'phase': 'RECOVERY_REPLAY_WAITING',
                        'createdAt': utc_now(),
                        'updatedAt': utc_now(),
                        'lastProgressAt': None,
                    })

                created = utc_now()
                recovery_side_effect = f'chat.send:recovery:{source_run_id}:{source_job_id}'
                recovery_logical_id, recovery_side_effect = self._logical_identity(
                    source_run_id, recovery_side_effect, None)
                job = {
                    'schemaVersion': 1,
                    'jobId': new_job_id,
                    'runId': source_run_id,
                    'createdAt': created,
                    'updatedAt': created,
                    'status': 'QUEUED',
                    'dispatchEpoch': self.dispatch_epoch,
                    'mode': source.get('mode') or 'open',
                    'aggregateMaxBytes': source.get('aggregateMaxBytes'),
                    'packagingPolicy': source.get('packagingPolicy'),
                    'stallTimeoutSeconds': source.get('stallTimeoutSeconds') or 120,
                    'target': {
                        'endpointId': target.get('endpointId'),
                        'browserEpoch': target.get('browserEpoch'),
                        'tabId': int(tab_id),
                        'url': target_url or page_url,
                        'chatType': target.get('chatType'),
                        'conversationId': target.get('conversationId'),
                        'projectId': target.get('projectId'),
                        'chatLabel': target.get('chatLabel'),
                    },
                    'logicalDeliveryId': recovery_logical_id,
                    'sideEffectKey': recovery_side_effect,
                    'deliverySessionId': source.get('deliverySessionId'),
                    'message': str(source.get('message') or ''),
                    'messageState': 'PENDING',
                    'messageError': None,
                    'messageInsertedAt': None,
                    'conversationBaseline': None,
                    'consumedAt': None,
                    'consumedReason': None,
                    'sendState': 'NOT_REQUESTED',
                    'sendError': None,
                    'claimedBy': None,
                    'claimLeaseToken': None,
                    'claimHeartbeatAt': None,
                    'claimExpiresAt': None,
                    'claimLeaseSeconds': CLAIM_LEASE_SECONDS,
                    'attachments': attachments,
                    'missingReports': list(source.get('missingReports') or []),
                    'reportCount': int(source.get('reportCount') or 0),
                    'recoveryReplay': True,
                    'recoveryOf': {
                        'runId': source_run_id,
                        'jobId': source_job_id,
                        'status': source_status,
                    },
                    'recoverySourceResolution': source_resolution,
                    'recoveryReason': str(reason or 'LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD'),
                    'recoveryFailureKey': str(failure_key or ''),
                    'recoveryFailureRowIndex': str(failure_row_index or ''),
                    'recoveryRequestedAt': created,
                }

                job['deliveryManifest'] = self._build_delivery_manifest(
                    delivery_id=new_job_id,
                    logical_delivery_id=recovery_logical_id,
                    side_effect_key=recovery_side_effect,
                    delivery_session_id=job.get('deliverySessionId'),
                    target=job['target'],
                    message=job['message'],
                    attachments=attachments,
                )
                job['deliveryManifestSha256'] = self._manifest_digest(job['deliveryManifest'])
                saved = self.save_job(job)
                saved['supersededOlderJobs'] = self.supersede_older_jobs_for_tab(
                    int(tab_id),
                    source_run_id,
                    new_job_id,
                )
                return self.save_job(saved)

            except Exception:
                shutil.rmtree(new_job_dir, ignore_errors=True)
                raise

    def pause_unfinished_jobs_after_restart(self) -> list[dict[str, Any]]:
        """Pause historical delivery work so a backend restart can never replay it."""
        changed: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return changed

        now = utc_now()
        with self.lock:
            for run_dir in self.data_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                delivery_root = run_dir / 'executor' / 'delivery'
                if not delivery_root.is_dir():
                    continue

                for path in delivery_root.iterdir():
                    job_file = path / 'job.json'
                    if not job_file.is_file():
                        continue

                    job = self._load_json(job_file, {})
                    if not isinstance(job, dict):
                        continue

                    status = str(job.get('status') or '')
                    if status in TERMINAL_JOB_STATES:
                        continue

                    # Jobs already created by this exact Console process are live.
                    if str(job.get('dispatchEpoch') or '') == self.dispatch_epoch:
                        continue

                    for attachment in job.get('attachments') or []:
                        state = str(attachment.get('state') or '')
                        if state in ACTIVE_ATTACHMENT_STATES:
                            attachment['state'] = 'STALLED'
                            attachment['phase'] = 'PAUSED_AFTER_RESTART'
                            attachment['error'] = 'Backend restarted during delivery; explicit resume required'
                            attachment['finishedAt'] = now
                            attachment['updatedAt'] = now

                    job['status'] = PAUSED_JOB_STATE
                    job['pausedAt'] = now
                    job['pauseReason'] = 'BACKEND_RESTART'
                    job['pausedFromDispatchEpoch'] = job.get('dispatchEpoch')
                    job['dispatchEpoch'] = None
                    job['claimedBy'] = None
                    job['clientHeartbeatAt'] = None
                    job['claimLeaseToken'] = None
                    job['claimHeartbeatAt'] = None
                    job['claimExpiresAt'] = None

                    # Never replay a pending Send click after a backend restart.
                    if str(job.get('sendState') or '') == 'SEND_REQUESTED':
                        job['sendState'] = 'NOT_REQUESTED'
                        job['sendError'] = 'Send request cleared after backend restart; explicit send required'

                    atomic_write_json(self.job_path(str(job.get('runId') or ''), str(job.get('jobId') or '')), job)
                    changed.append(job)

        return changed

    @staticmethod
    def _delivery_identity(job: dict[str, Any]) -> tuple[str, str] | None:
        logical = job.get('logicalDeliveryId')
        side = job.get('sideEffectKey')
        if not isinstance(logical, str) or not logical.strip():
            return None
        if not isinstance(side, str) or not side.strip():
            return None
        return logical.strip(), side.strip()

    def supersede_older_jobs_for_tab(self, target_tab_id: int, keep_run_id: str, keep_job_id: str) -> int:
        """Retire only older attempts of the same logical delivery.

        Slice 2 temporarily retired every queued job for a tab.  Slice 4 makes
        supersession about logical side-effect identity instead: two independent
        deliveries to one conversation survive and are merely serialized by the
        browser-plane lease.  The lease/UNKNOWN protections introduced in slice
        2 remain unchanged.
        """
        changed = 0
        if not self.data_dir.is_dir():
            return changed
        with self.lock:
            keep = self.get_job(keep_run_id, keep_job_id)
            keep_identity = self._delivery_identity(keep)
            if keep_identity is None:
                return 0
            self.recover_expired_leases()
            for run_dir in self.data_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                delivery_root = run_dir / 'executor' / 'delivery'
                if not delivery_root.is_dir():
                    continue
                for path in delivery_root.iterdir():
                    job_file = path / 'job.json'
                    if not job_file.is_file():
                        continue
                    job = self._load_json(job_file, {})
                    if not isinstance(job, dict):
                        continue
                    if str(job.get('runId') or '') == str(keep_run_id) and str(job.get('jobId') or '') == str(keep_job_id):
                        continue
                    verdict, _why = self.classify_target(job, tab_id=target_tab_id)
                    if verdict != self.TARGET_MATCH:
                        continue
                    if self._delivery_identity(job) != keep_identity:
                        # Same browser target does not mean same logical effect.
                        continue
                    if str(job.get('status') or '') in TERMINAL_JOB_STATES:
                        continue
                    if self._manifest_error(job):
                        # Damaged identity/manifest is evidence, not a candidate
                        # for a terminal supersede write.
                        continue
                    kind, _detail = self.classify_lease(job)
                    if kind != self.LEASE_NONE:
                        continue
                    job['status'] = 'SUPERSEDED'
                    job['supersededAt'] = utc_now()
                    job['supersededBy'] = {
                        'runId': keep_run_id,
                        'jobId': keep_job_id,
                        'logicalDeliveryId': keep_identity[0],
                        'sideEffectKey': keep_identity[1],
                    }
                    self.save_job(job)
                    changed += 1
        return changed

    def outstanding_lease_for_tab(self, tab_id: int) -> dict[str, Any] | None:
        """The delivery that still owes this tab an outcome, if there is one.

        Single-flight is a property of the tab, not of one job: two jobs both
        addressed to the same browser tab cannot be performed at once, and the
        older one is not superseded while it holds a lease. Without this the
        newer job would simply be handed out next to the claimed one.

        Every state except NO_LEASE counts. EXPIRED used to be let through on
        the reasoning that recovery had already run — but recovery and this
        decision read the clock separately, so a lease that was ACTIVE during
        the pass, and therefore correctly left alone, can be EXPIRED by the
        time it is classified here. An expired lease that has not been through
        recovery is an outcome nobody has accounted for, which is precisely
        what must not open the tab. Blocking it costs one poll: the next one
        recovers it first and then proceeds.
        """
        for job, error in self._iter_jobs_strict():
            if error is not None:
                # Unreadable is not empty. It may be the very job holding the
                # lease, so the tab is treated as busy until someone can read it.
                return {'runId': None, 'jobId': None, 'lease': self.LEASE_INVALID,
                        'reason': f'unreadable job: {error}'}
            verdict, why = self.classify_target(job, tab_id=tab_id)
            if verdict == self.TARGET_UNPROVABLE:
                # Whose tab this job belongs to cannot be read, so it may be
                # this one, and it may be holding the outcome this tab is
                # waiting for. The same answer an unreadable job already gets.
                return {'runId': job.get('runId'), 'jobId': job.get('jobId'),
                        'lease': self.LEASE_INVALID, 'reason': f'unreadable target: {why}'}
            if verdict == self.TARGET_OTHER:
                continue
            if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                continue
            kind, detail = self.classify_lease(job)
            if kind != self.LEASE_NONE:
                return {'runId': job.get('runId'), 'jobId': job.get('jobId'),
                        'lease': kind, 'reason': detail or kind}
        return None

    def _derive_job_status(self, job: dict[str, Any]) -> None:
        if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
            return
        states = [str(x.get('state') or '') for x in job.get('attachments') or []]
        send_state = str(job.get('sendState') or 'NOT_REQUESTED')
        if send_state == 'SENT':
            job['status'] = 'SENT'
            return
        if send_state == 'SEND_ERROR':
            job['status'] = 'SEND_ERROR'
            return
        if send_state == 'SEND_REQUESTED':
            job['status'] = 'SEND_REQUESTED'
            return
        if any(x in ACTIVE_ATTACHMENT_STATES for x in states):
            job['status'] = 'UPLOADING'
            return
        if any(x in RETRYABLE_ATTACHMENT_STATES for x in states):
            job['status'] = 'PARTIAL'
            return
        if any(x in PENDING_ATTACHMENT_STATES for x in states):
            job['status'] = 'QUEUED'
            return
        all_ready = all(x in READY_ATTACHMENT_STATES for x in states) if states else True
        if all_ready and job.get('messageState') == 'INSERTED':
            job['status'] = 'READY_TO_SEND'
        elif all_ready:
            job['status'] = 'FILES_READY'
        else:
            job['status'] = 'QUEUED'


    # ---- rollout mode -----------------------------------------------------

    def _rollout_path(self) -> Path:
        path = self.data_dir.parent / 'runtime' / 'delivery-rollout.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _unsafe_state(reason: str) -> dict[str, Any]:
        """State that cannot be trusted at all, as distinct from a latched drain.

        These are different things and were conflated. A valid DRAIN with the
        latch set still permits events for already-claimed work, so presenting
        an unreadable file as a latched DRAIN reopened the delivery plane
        exactly when the persisted BARRIER had been damaged.
        """
        return {'mode': ROLLOUT_DRAIN, 'drainId': None, 'unsafe': True,
                'valid': False, 'stateError': reason,
                'unsafeReasons': [reason], 'startedAt': None}

    @staticmethod
    def _aware_ts(value: Any) -> bool:
        return decision_dt(value) is not None

    def rollout_state(self) -> dict[str, Any]:
        """Read the rollout state, treating anything unexpected as unsafe.

        Filling in defaults for a partially written DRAIN would invent the very
        fact the latch exists to preserve: this writer always stores drainId,
        startedAt, unsafe and unsafeReasons together, so a DRAIN missing any of
        them was not written by it.
        """
        path = self._rollout_path()
        if not path.is_file():
            return {'mode': ROLLOUT_OPEN, 'drainId': None, 'unsafe': False,
                    'valid': True, 'unsafeReasons': [], 'startedAt': None}
        try:
            body = json.loads(path.read_text('utf-8'))
        except Exception:
            return self._unsafe_state('rollout state unreadable')
        if not isinstance(body, dict):
            return self._unsafe_state('rollout state is not an object')
        mode = body.get('mode')
        if mode not in ROLLOUT_MODES:
            return self._unsafe_state(f'unknown rollout mode {mode!r}')
        if mode == ROLLOUT_OPEN:
            # Absence of the file means OPEN; this writer never stores an OPEN
            # file. So a stored OPEN is not a canonical state, and accepting it
            # meant that damaging one field of a valid BARRIER — the word
            # BARRIER itself — reopened the delivery plane while the rest of the
            # record still said otherwise.
            return self._unsafe_state(
                'rollout state stores OPEN, which this writer never produces')
        if not isinstance(body.get('drainId'), str) or not body['drainId'].strip():
            return self._unsafe_state('rollout state has no drainId')
        if not self._aware_ts(body.get('startedAt')):
            return self._unsafe_state('rollout startedAt is not a timezone-aware timestamp')
        if not isinstance(body.get('unsafe'), bool):
            return self._unsafe_state('rollout state has no unsafe flag')
        reasons = body.get('unsafeReasons')
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            return self._unsafe_state('rollout unsafeReasons is not a list of strings')
        # This writer never stores one without the other. A cleared flag beside
        # recorded reasons is not a safe drain; it is a state nobody wrote.
        if bool(body['unsafe']) != bool(reasons):
            return self._unsafe_state(
                'rollout unsafe flag contradicts unsafeReasons')
        # Canonical shapes, symmetric on purpose: a BARRIER carries enteredAt
        # and a DRAIN does not. Without the second half, damaging one word of a
        # valid BARRIER turned it into an acceptable DRAIN with the barrier's
        # own timestamp still inside.
        if mode == ROLLOUT_BARRIER and not self._aware_ts(body.get('enteredAt')):
            return self._unsafe_state('barrier enteredAt is not a timezone-aware timestamp')
        if mode == ROLLOUT_DRAIN and body.get('enteredAt') is not None:
            return self._unsafe_state('drain state carries a barrier enteredAt')
        body['valid'] = True
        return body

    def _write_rollout(self, body: dict[str, Any]) -> None:
        atomic_write_json(self._rollout_path(), body)

    def begin_drain(self) -> dict[str, Any]:
        """Start a drain pass with its own identity.

        Restarting the pass is what clears the latch, and only an operator can
        do that: an automatic reset would turn "we lost track of an outcome"
        into "there is nothing outstanding".
        """
        state = {'mode': ROLLOUT_DRAIN, 'drainId': uuid.uuid4().hex,
                 'startedAt': utc_now(), 'unsafe': False, 'unsafeReasons': []}
        self._write_rollout(state)
        return state

    def mark_unsafe(self, reason: str) -> dict[str, Any]:
        """Latch the drain as unsafe. Monotonic within a pass."""
        state = self.rollout_state()
        if state.get('mode') != ROLLOUT_DRAIN:
            return state
        reasons = list(state.get('unsafeReasons') or [])
        if reason not in reasons:
            reasons.append(reason)
        state['unsafe'] = True
        state['unsafeReasons'] = reasons
        self._write_rollout(state)
        return state


    # ---- lease evidence during a drain ------------------------------------

    TARGET_MATCH = 'MATCH'
    TARGET_OTHER = 'OTHER'
    TARGET_UNPROVABLE = 'UNPROVABLE'

    def _require_target_tab(self, job: dict[str, Any], requested_tab: Any) -> None:
        """This caller's tab is the tab this job is addressed to, provably.

        Both browser-facing paths ask the same question, so both ask it the
        same way. Anything other than a proven match is a refusal: a target
        nobody can read is not authorization, and neither is one that only
        looks like a match after coercion.
        """
        try:
            tab_id = int(requested_tab)
        except (TypeError, ValueError):
            raise DeliveryError('wrong tabId for delivery job: no tab given')
        verdict, why = self.classify_target(job, tab_id=tab_id)
        if verdict != self.TARGET_MATCH:
            raise DeliveryError(f'wrong tabId for delivery job: {why or verdict}')

    def _require_target_endpoint(self, job: dict[str, Any], endpoint_id: Any) -> None:
        """Require the endpoint identity proven by the browser barrier.

        tabId is only a browser-local locator and can be reused after a tab
        closes.  When a caller supplies endpointId, a different generation of
        the same tab must not claim, report on, or read an older delivery.
        """
        if endpoint_id is None:
            return
        requested = str(endpoint_id or '').strip()
        target = job.get('target') if isinstance(job.get('target'), dict) else {}
        stored = str(target.get('endpointId') or '').strip()
        if not requested or not stored:
            raise DeliveryError('delivery target endpoint cannot be proved')
        if requested != stored:
            raise DeliveryError('delivery job belongs to another endpoint')

    def classify_target(self, job: dict[str, Any], *, tab_id: int,
                        page_url: str = '') -> tuple[str, str]:
        """Whether this stored job is addressed to this tab and page.

        Three answers, for the same reason the lease and the submitted time
        have three. A stored target saying tab 8 while tab 7 is asking is a
        fact: the job belongs elsewhere and is rightly skipped. A target that
        is missing, is not an object, has no tabId, or has one that is not a
        number proves nothing of the sort — and it used to be read through a
        shrug that turned all of it into `{}` and then into tab `-1`, which
        compares unequal to every real tab. An address nobody can read became
        somebody else's address, and the older delivery behind it was named
        the proven latest. The unusable value had a second exit: `int('bad')`
        raised straight past the three-valued answer.

        An empty stored url is the writer's own way of recording a target with
        no page, so it keeps matching. A url of the wrong type does not: making
        text out of it invents a page and then rules the job out for being on
        the wrong one.
        """
        raw = job.get('target')
        if not isinstance(raw, dict):
            return self.TARGET_UNPROVABLE, f'target is not an object: {raw!r}'
        if 'tabId' not in raw:
            return self.TARGET_UNPROVABLE, 'target has no tabId'
        stored_tab = raw.get('tabId')
        if isinstance(stored_tab, bool) or not isinstance(stored_tab, (int, str)):
            return self.TARGET_UNPROVABLE, f'target tabId is not a number: {stored_tab!r}'
        try:
            stored_tab = int(stored_tab)
        except (TypeError, ValueError):
            return self.TARGET_UNPROVABLE, f'target tabId is not a number: {raw.get("tabId")!r}'
        if stored_tab != int(tab_id):
            return self.TARGET_OTHER, f'target tabId is {stored_tab}'

        if 'url' not in raw:
            # The writer stores a url on every target, so an absent one is
            # damage rather than the canonical empty. Answering both the same
            # way made a missing page into a page that matches anything: a
            # delivery addressed elsewhere became the proven latest here, and
            # a queued job for another page could be handed to this one.
            return self.TARGET_UNPROVABLE, 'target has no url'
        stored_url = raw['url']
        if not isinstance(stored_url, str):
            return self.TARGET_UNPROVABLE, f'target url is not a string: {stored_url!r}'
        if stored_url == '':
            # The writer's own record of a target with no page: it matches, and
            # it is the only shape of "no page" that does.
            return self.TARGET_MATCH, ''
        if page_url and not self._same_page_url(stored_url, page_url):
            return self.TARGET_OTHER, f'target url is {stored_url}'
        return self.TARGET_MATCH, ''

    SUBMITTED_FOUND = 'FOUND'
    SUBMITTED_ABSENT = 'ABSENT'
    SUBMITTED_UNPROVABLE = 'UNPROVABLE'

    LEASE_NONE = 'NO_LEASE'
    LEASE_ACTIVE = 'ACTIVE'
    LEASE_EXPIRED = 'EXPIRED'
    LEASE_INVALID = 'INVALID'

    def classify_lease(self, job: dict[str, Any]) -> tuple[str, str]:
        """Classify the lease trace on disk, not merely whether it is live now.

        `_lease_is_active` answers False for a missing lease and for a
        contradictory one alike, and the drain read that as "nothing here".
        A half-written lease is an unknown outcome, not an absent one, so the
        two must be told apart before the boundary closes over them.
        """
        token = job.get('claimLeaseToken')
        expires_raw = job.get('claimExpiresAt')
        # CLAIM writes these four together and _clear_lease removes them
        # together, so any subset is a half-written trace, not an absent lease.
        # clientHeartbeatAt is deliberately excluded: it outlives _clear_lease.
        claimed_by = job.get('claimedBy')
        present = {
            'claimLeaseToken': isinstance(token, str) and token.strip() != '',
            'claimExpiresAt': isinstance(expires_raw, str) and expires_raw.strip() != '',
            'claimHeartbeatAt': isinstance(job.get('claimHeartbeatAt'), str)
                                and str(job.get('claimHeartbeatAt')).strip() != '',
            'claimedBy': isinstance(claimed_by, dict) and bool(claimed_by),
        }
        if not any(present.values()):
            return self.LEASE_NONE, ''
        missing = [name for name, ok in present.items() if not ok]
        if missing:
            return self.LEASE_INVALID, 'incomplete lease trace, missing ' + ', '.join(missing)
        if not self._aware_ts(job.get('claimHeartbeatAt')):
            return self.LEASE_INVALID, 'claimHeartbeatAt is not a timezone-aware timestamp'
        # claimedBy is the provenance CLAIM records: which tab took the lease,
        # where, when, and under which token. Validated against that shape
        # rather than a simpler one — a classifier that disagrees with the
        # writer rejects leases the server itself created.
        if not isinstance(claimed_by.get('tabId'), int) or isinstance(claimed_by.get('tabId'), bool):
            return self.LEASE_INVALID, 'claimedBy.tabId is not an integer'
        if not isinstance(claimed_by.get('url'), str):
            return self.LEASE_INVALID, 'claimedBy.url is not a string'
        if not self._aware_ts(claimed_by.get('at')):
            return self.LEASE_INVALID, 'claimedBy.at is not a timezone-aware timestamp'
        claimed_token = claimed_by.get('leaseToken')
        if not isinstance(claimed_token, str) or claimed_token.strip() != str(token).strip():
            return self.LEASE_INVALID, 'claimedBy.leaseToken disagrees with claimLeaseToken'
        has_token = True
        has_expiry = True
        expires = iso_dt(expires_raw)
        if expires is None:
            return self.LEASE_INVALID, f'unreadable claimExpiresAt {expires_raw!r}'
        if expires.tzinfo is None or expires.utcoffset() is None:
            return self.LEASE_INVALID, f'claimExpiresAt has no timezone: {expires_raw!r}'
        if expires > utc_now_dt():
            return self.LEASE_ACTIVE, ''
        return self.LEASE_EXPIRED, ''

    def _drain_reconcile(self) -> None:
        """Latch anything a drain cannot account for, across every process.

        Deliberately ignores dispatchEpoch. `recover_expired_leases` skips jobs
        of a previous epoch, so a console restarted mid-drain stopped seeing the
        lease it was waiting on: while alive it blocked the barrier, and the
        moment it expired it vanished from the check entirely and the barrier
        opened. Work outstanding from the old process is still outstanding.
        """
        if str(self.rollout_state().get('mode') or '') != ROLLOUT_DRAIN:
            return
        for job, error in self._iter_jobs_strict():
            if error is not None:
                self.mark_unsafe(f'unreadable delivery job during drain: {error}')
                continue
            if str(job.get('status') or '') in TERMINAL_JOB_STATES:
                continue
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_EXPIRED:
                self.mark_unsafe(
                    f"lease expired during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')} status={job.get('status')}")
            elif kind == self.LEASE_INVALID:
                self.mark_unsafe(
                    f"invalid lease state during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')}: {detail}")

    def drain_status(self) -> dict[str, Any]:
        """What still stands between this drain and the barrier."""
        state = self.rollout_state()
        outstanding: list[dict[str, Any]] = []
        for job, error in self._iter_jobs_strict():
            if error is not None:
                # A delivery job that cannot be read is an unknown outcome, not
                # an absent one. Tolerant loading turned it into {} and it
                # disappeared from the check entirely.
                outstanding.append({'runId': None, 'jobId': None,
                                    'reason': f'unreadable job: {error}'})
                continue
            status = str(job.get('status') or '')
            if status in TERMINAL_JOB_STATES:
                kind, detail = self.classify_lease(job)
                if kind != self.LEASE_NONE:
                    # A finished job still holding a lease is a contradiction,
                    # not silence: either the lease was never ended or the job
                    # was terminated under someone who still held it.
                    outstanding.append({**{'runId': job.get('runId'), 'jobId': job.get('jobId')},
                                        'reason': f'terminal job still holding a {kind} lease'})
                continue
            ref = {'runId': job.get('runId'), 'jobId': job.get('jobId')}
            # Browser quiet is not only about leases: an attachment still being
            # fetched or uploaded is a browser operation in flight, and closing
            # the boundary over it would cut the operation the design says must
            # finish first.
            for attachment in job.get('attachments') or []:
                state_name = str(attachment.get('state') or '')
                if state_name in ACTIVE_ATTACHMENT_STATES:
                    outstanding.append({**ref, 'reason': f'attachment {state_name}',
                                        'attachmentId': attachment.get('attachmentId')})
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_ACTIVE:
                outstanding.append({**ref, 'reason': 'claimed'})
            elif kind == self.LEASE_EXPIRED:
                outstanding.append({**ref, 'reason': 'lease expired, outcome unknown'})
            elif kind == self.LEASE_INVALID:
                outstanding.append({**ref, 'reason': f'invalid lease state: {detail}'})
            elif status == 'DISPATCHING':
                outstanding.append({**ref, 'reason': 'dispatching'})
        return {'mode': state.get('mode'), 'drainId': state.get('drainId'),
                'unsafe': bool(state.get('unsafe')),
                'unsafeReasons': list(state.get('unsafeReasons') or []),
                'outstanding': outstanding,
                'barrierAllowed': (state.get('mode') == ROLLOUT_DRAIN
                                   and not state.get('unsafe') and not outstanding)}

    def enter_barrier(self) -> dict[str, Any]:
        """Close the boundary, or refuse and say what is in the way.

        Recovery runs here rather than being expected beforehand. A lease that
        expired during the drain stops counting as active the moment it expires,
        so a barrier evaluated without recovery sees a quiet queue and closes
        over an outcome nobody recorded. Safety must not depend on the caller
        remembering the right order.
        """
        self.recover_expired_leases()
        # Across every process, not only this one's epoch.
        self._drain_reconcile()
        status = self.drain_status()
        if not status['barrierAllowed']:
            raise DeliveryError(
                'BARRIER_REFUSED: ' + json.dumps({'unsafe': status['unsafe'],
                                                  'unsafeReasons': status['unsafeReasons'],
                                                  'outstanding': status['outstanding']},
                                                 ensure_ascii=False))
        state = self.rollout_state()
        state['mode'] = ROLLOUT_BARRIER
        state['enteredAt'] = utc_now()
        self._write_rollout(state)
        return state

    def _iter_jobs(self):
        for job, error in self._iter_jobs_strict():
            if error is None:
                yield job

    def _iter_jobs_strict(self):
        """Every persisted delivery job, reporting the ones that cannot be read."""
        if not self.data_dir.is_dir():
            return
        for run_dir in sorted(self.data_dir.iterdir()):
            delivery_root = run_dir / 'executor' / 'delivery'
            if not delivery_root.is_dir():
                continue
            for job_dir in sorted(delivery_root.iterdir()):
                job_file = job_dir / 'job.json'
                if not job_file.is_file():
                    continue
                try:
                    job = json.loads(job_file.read_text('utf-8'))
                except Exception as exc:
                    yield None, f'{job_file}: {exc}'
                    continue
                if not isinstance(job, dict) or not job.get('jobId'):
                    yield None, f'{job_file}: not a delivery job'
                    continue
                # Only what browser quiet depends on, not the whole schema.
                attachments = job.get('attachments', [])
                if not isinstance(attachments, list):
                    yield None, f'{job_file}: attachments is not a list'
                    continue
                if any(not isinstance(a, dict) for a in attachments):
                    yield None, f'{job_file}: attachments contains a non-object'
                    continue
                if str(job.get('status') or '') in TERMINAL_JOB_STATES and any(
                        str(a.get('state') or '') in ACTIVE_ATTACHMENT_STATES for a in attachments):
                    # A finished job cannot still be uploading. Reading this as
                    # quiet would take a contradiction for proof of silence.
                    yield None, (f'{job_file}: terminal job with an attachment still in flight')
                    continue
                yield job, None

    def _lease_is_active(self, job: dict[str, Any]) -> bool:
        """One source of truth for lease liveness.

        Comparing the timestamp here as well left a second place that could meet
        a naive value and raise a bare TypeError, and a second definition of
        "active" that could drift from the classifier.
        """
        return self.classify_lease(job)[0] == self.LEASE_ACTIVE

    def _require_live_lease(self, job: dict[str, Any], lease_token: str) -> None:
        """Every non-CLAIM operation needs a live lease that this client holds.

        Validation only: this leaves the job exactly as it found it. Renewal is
        a separate act, because a caller that does not persist the job cannot
        renew anything — `attachment_chunk` called the mutating helper and never
        saved, so the code read as a renewal while the stored lease went on
        expiring on its original schedule.

        The old comparison matched an empty stored token against an empty
        requested one and, finding no expiry to object to, wrote a fresh one:
        a lease conjured out of nothing. During a drain that let unclaimed work
        keep moving, and RELEASE could erase a contradictory trace the latch was
        holding, opening the barrier over it.
        """
        kind, detail = self.classify_lease(job)
        if kind == self.LEASE_NONE:
            raise DeliveryError('DELIVERY_NOT_LEASED: job has no delivery lease')
        if kind == self.LEASE_EXPIRED:
            self._latch_if_draining_reason(
                job, f"event on an expired lease: run={job.get('runId')} job={job.get('jobId')}")
            raise DeliveryError('delivery lease expired')
        if kind == self.LEASE_INVALID:
            self._latch_if_draining_reason(
                job, f"event on an invalid lease state: run={job.get('runId')} "
                     f"job={job.get('jobId')}: {detail}")
            raise DeliveryError(f'DELIVERY_LEASE_INVALID: {detail}')
        requested = str(lease_token or '').strip()
        if not requested or str(job.get('claimLeaseToken') or '').strip() != requested:
            raise DeliveryError('delivery lease token mismatch')

    def _touch_lease(self, job: dict[str, Any], lease_token: str) -> None:
        """Validate, then renew. The caller must persist the job afterwards.

        Only delivery events take this path, and every one of them ends in
        `save_job`. Reading attachment bytes does not: `attachment_chunk`
        validates and reads, and the lease is renewed by the client's HEARTBEAT
        like any other lease in the system. One renewal path, and it is a
        persisted one.
        """
        self._require_live_lease(job, lease_token)
        now = utc_now()
        job['claimHeartbeatAt'] = now
        job['clientHeartbeatAt'] = now
        job['claimExpiresAt'] = utc_after(CLAIM_LEASE_SECONDS)

    def _clear_lease(self, job: dict[str, Any]) -> None:
        job['claimedBy'] = None
        job['claimLeaseToken'] = None
        job['claimHeartbeatAt'] = None
        job['claimExpiresAt'] = None

    def _recover_active_attachment(self, attachment: dict[str, Any], reason: str) -> bool:
        state = str(attachment.get('state') or '')
        if state not in ACTIVE_ATTACHMENT_STATES:
            return False

        attachment['updatedAt'] = utc_now()
        attachment['finishedAt'] = utc_now()

        if state in {'CHAT_UPLOADING', 'CLAUDE_UPLOADING'}:
            attachment['state'] = 'STALLED'
            attachment['phase'] = 'CHAT_UPLOAD_INTERRUPTED_NO_AUTO_RETRY'
            attachment['error'] = (
                f'{reason}; automatic re-attach is disabled because the file may '
                f'already exist in the target chat. Use explicit manual retry if required.'
            )
            return True

        recoveries = int(attachment.get('autoRecoveries') or 0) + 1
        attachment['autoRecoveries'] = recoveries

        if recoveries <= MAX_AUTO_RECOVERIES:
            attachment['state'] = 'RECOVER_PENDING'
            attachment['phase'] = 'AUTO_RECOVER_FETCH_PENDING'
            attachment['error'] = reason
        else:
            attachment['state'] = 'STALLED'
            attachment['phase'] = 'AUTO_RECOVER_LIMIT_REACHED'
            attachment['error'] = (
                f'{reason}; automatic recovery limit reached '
                f'({MAX_AUTO_RECOVERIES})'
            )
        return True

    def _latch_if_draining_reason(self, job: dict[str, Any], reason: str) -> None:
        if str(self.rollout_state().get('mode') or '') == ROLLOUT_DRAIN:
            self.mark_unsafe(reason)

    def _latch_if_draining(self, job: dict[str, Any]) -> None:
        """A lease that expired during a drain leaves an outcome nobody knows.

        Latching here rather than at barrier time is deliberate: by the time the
        barrier is checked the lease is gone from the table, and an empty table
        would otherwise read as proof that everything finished.
        """
        state = self.rollout_state()
        if str(state.get('mode') or '') != ROLLOUT_DRAIN:
            return
        self.mark_unsafe(
            f"lease expired during drain: run={job.get('runId')} job={job.get('jobId')} "
            f"status={job.get('status')}")

    def recover_expired_leases(self) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return changed

        now_dt = utc_now_dt()
        with self.lock:
            for run_dir in self.data_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                delivery_root = run_dir / 'executor' / 'delivery'
                if not delivery_root.is_dir():
                    continue

                for path in delivery_root.iterdir():
                    job_file = path / 'job.json'
                    if not job_file.is_file():
                        continue
                    job = self._load_json(job_file, {})
                    if not isinstance(job, dict):
                        continue

                    if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                        continue
                    if str(job.get('dispatchEpoch') or '') != self.dispatch_epoch:
                        continue

                    # Classified rather than compared directly: a naive
                    # timestamp used to meet an aware one here and raise a bare
                    # TypeError from inside recovery. An unclassifiable lease is
                    # not recovered — it is left for the drain to latch.
                    kind, _detail = self.classify_lease(job)
                    if kind != self.LEASE_EXPIRED:
                        continue

                    for attachment in job.get('attachments') or []:
                        self._recover_active_attachment(
                            attachment,
                            'Browser delivery lease expired before operation completed'
                        )

                    if str(job.get('sendState') or '') == 'SEND_REQUESTED':
                        job['sendState'] = 'SEND_ERROR'
                        job['sendError'] = (
                            'Delivery lease expired while Send was pending; explicit Send is required'
                        )

                    # Latch before the trace is cleared: afterwards the lease
                    # is gone from the table and an empty table would read as
                    # proof that the delivery finished.
                    self._latch_if_draining(job)
                    self._clear_lease(job)
                    job['leaseRecoveredAt'] = utc_now()
                    self.save_job(job)
                    changed.append(job)

        return changed

    def poll_for_tab(self, tab_id: int, page_url: str, endpoint_id: str | None = None) -> dict[str, Any] | None:
        mode = str(self.rollout_state().get('mode') or ROLLOUT_OPEN)
        if mode in (ROLLOUT_DRAIN, ROLLOUT_BARRIER):
            # No new work is handed out and no new claim may be taken. Events
            # for work already claimed still arrive through update_from_client,
            # which is what lets a claimed delivery finish rather than being
            # abandoned mid-flight.
            self.recover_expired_leases()
            return None
        # Recovery and the decision are one critical section. They classify the
        # same leases from two separate clock readings, so anything that can
        # change between them changes the answer: a claim taken by another
        # request after the gate has passed would put a second delivery into
        # the tab the gate had just found free.
        with self.lock:
            self.recover_expired_leases()
            if not self.data_dir.is_dir():
                return None
            # One delivery per tab at a time. A newer job is created while an
            # older one is claimed — the ordinary case now that the older one
            # is no longer superseded out from under its lease — and handing
            # the newer one out would put two deliveries into the same tab,
            # with the outcome of the first still owed.
            if self.outstanding_lease_for_tab(tab_id) is not None:
                return None
            # The supersede that `create_job` had to skip is a postponement,
            # not a cancellation. It runs once, while the newer job is being
            # written, and at that moment the older one is protected by its
            # lease — so nothing retires it and nothing used to come back to
            # it. The older delivery then waited behind the newer one and
            # became eligible again the moment the newer one was sent: a chat
            # received the superseded content after the current content.
            #
            # Here is where the postponement is redeemed. The gate above has
            # just proved every job of this tab is at NO_LEASE, so the safety
            # rule and the retirement do not overlap: nothing with an
            # outstanding outcome can be retired from this call.
            self._retire_superseded_for_tab(tab_id)
            return self._select_job_for_tab(tab_id, page_url, endpoint_id)

    def prepare_order_for_tab(self, tab_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        """This tab's open deliveries, newest Prepare first — or a refusal.

        Both decisions that rest on Prepare order come through here, because
        the order was being taken from `createdAt` compared as a string. That
        is the time invariant broken in the one place where breaking it is not
        a misordering: `SUPERSEDED` is terminal, and a malformed value sorts
        above every real ISO timestamp, so the stale job became the keeper and
        the genuinely newer delivery was destroyed.

        Refusal is a value with a reason. Three cases produce it, and each is
        UNKNOWN rather than absent:

          - a job that cannot be read at all;
          - a `createdAt` that is missing, malformed or naive;
          - two newest jobs sharing an instant, which is provable time that
            still establishes no order. Falling back on `Path.iterdir` order
            would make the filesystem the arbiter of which delivery survives.

        A refusal stops the tab until an operator resolves it. That is the same
        answer an unexplained lease already gets, and it is recoverable: repair
        the stored value and the next poll proceeds.
        """
        rows: list[tuple[datetime, dict[str, Any]]] = []
        for job, error in self._iter_jobs_strict():
            if error is not None:
                return None, f'unreadable delivery job: {error}'
            verdict, why = self.classify_target(job, tab_id=tab_id)
            if verdict == self.TARGET_UNPROVABLE:
                return None, (f"target cannot be read: run={job.get('runId')} "
                              f"job={job.get('jobId')}: {why}")
            if verdict == self.TARGET_OTHER:
                continue
            if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                continue
            manifest_error = self._manifest_error(job)
            if manifest_error:
                return None, (f"delivery manifest cannot be proved: run={job.get('runId')} "
                              f"job={job.get('jobId')}: {manifest_error}")
            if self._delivery_identity(job) is None:
                return None, (f"logical delivery identity cannot be read: "
                              f"run={job.get('runId')} job={job.get('jobId')}")
            created = decision_dt(job.get('createdAt'))
            if created is None:
                return None, (f"createdAt is not a timezone-aware timestamp: "
                              f"run={job.get('runId')} job={job.get('jobId')} "
                              f"value={job.get('createdAt')!r}")
            rows.append((created, job))
        rows.sort(key=lambda row: row[0], reverse=True)
        if len(rows) > 1 and rows[0][0] == rows[1][0]:
            return None, (f"two Prepares share the newest createdAt "
                          f"({rows[0][0].isoformat()}), so no newest can be proven")
        return [job for _created, job in rows], ''

    def _retire_superseded_for_tab(self, tab_id: int) -> int:
        """Redeem deferred supersession inside each logical-delivery group.

        The tab gate has proved there is no outstanding lease.  We still do
        not collapse independent deliveries into one: each identity keeps its
        newest Prepare, and only older attempts of that identity are retired.
        """
        order, _reason = self.prepare_order_for_tab(tab_id)
        if not order:
            return 0
        newest_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
        for job in order:  # newest first
            identity = self._delivery_identity(job)
            if identity is None:
                return 0
            newest_by_identity.setdefault(identity, job)
        changed = 0
        for newest in newest_by_identity.values():
            changed += self.supersede_older_jobs_for_tab(
                tab_id, str(newest.get('runId') or ''), str(newest.get('jobId') or ''))
        return changed

    def _select_job_for_tab(self, tab_id: int, page_url: str, endpoint_id: str | None = None) -> dict[str, Any] | None:
        """The newest job for this tab that owes nothing and is owed nothing.

        The order comes from `prepare_order_for_tab`, which proves it, so a
        Prepare order that cannot be established hands out nothing rather than
        the job that happens to sort first. String comparison of `createdAt`
        used to decide this too, and the same malformed value that made a stale
        job the keeper also made it the offer.

        Only NO_LEASE is eligible. This repeats the gate above deliberately:
        the gate answers about the tab, this answers about the job, and a state
        that reaches here with any lease trace at all — including one that
        expired between the two — is an outcome nobody has recorded.
        """
        order, _reason = self.prepare_order_for_tab(tab_id)
        if not order:
            return None
        for job in order:                       # newest proven Prepare first
            target = job.get('target') if isinstance(job.get('target'), dict) else {}
            if endpoint_id is not None and str(target.get('endpointId') or '') != str(endpoint_id):
                # tabId is a browser-local locator and may be reused.  Once S4
                # has resolved a delivery to endpointId, a newer endpoint that
                # happens to occupy the same tab must not receive the old job.
                continue
            target_url = str(target.get('url') or '')
            if target_url and page_url and target_url.split('#', 1)[0] != page_url.split('#', 1)[0]:
                continue
            if str(job.get('dispatchEpoch') or '') != self.dispatch_epoch:
                continue
            kind, _detail = self.classify_lease(job)
            if kind != self.LEASE_NONE:
                # ACTIVE: someone is performing it. EXPIRED: it has not been
                # through recovery in this pass, so its outcome is unknown
                # rather than absent. INVALID: contradictory evidence needs an
                # operator, not another client — offering the job would only
                # produce a claim refused for the same reason.
                continue
            return job
        return None

    def update_from_client(self, run_id: str, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(run_id, job_id)

            # Authorization first, idempotence second. The terminal early return
            # used to stand above this check, so an endpoint could name any
            # finished delivery of any other tab and be answered 200 with the
            # job body — the caller's own tab was never established. A terminal
            # state is a reason to do nothing, not a reason to skip asking who
            # is calling.
            #
            # The stored target is read by the one classifier, not by `int()`
            # here. `int(True)` is 1, so a corrupted tabId used to answer as a
            # perfectly good tab number and hand the job to it, and `int('bad')`
            # left through an exception instead of a refusal.
            self._require_target_tab(job, body.get('tabId'))
            self._require_target_endpoint(
                job, body.get('endpointId') if 'endpointId' in body else None)
            # The manifest is the immutable authorization envelope for the
            # external delivery.  Prove it before terminal idempotence or any
            # event mutation: a caller may not use a damaged persisted job as
            # either a successful no-op or a new side-effect attempt.
            self._require_manifest(job)

            if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                return job

            event_type = str(body.get('event') or '')
            if event_type == 'CLAIM':
                # A new claim is new work. Refusing it only in poll_for_tab left
                # the event route as a way to take one anyway, which is how a
                # drain could still be handed fresh outstanding deliveries after
                # it started. Checked before any job-specific validation, so an
                # unrelated complaint cannot answer in its place.
                mode = str(self.rollout_state().get('mode') or ROLLOUT_OPEN)
                if mode != ROLLOUT_OPEN:
                    raise DeliveryError(f'DELIVERY_CLAIM_REFUSED: rollout mode is {mode}')
            now = utc_now()

            if event_type == 'CLAIM':
                requested_token = str(body.get('leaseToken') or '').strip()
                if not requested_token:
                    raise DeliveryError('missing delivery lease token')

                current_token = str(job.get('claimLeaseToken') or '')
                kind, detail = self.classify_lease(job)
                if kind == self.LEASE_ACTIVE and current_token != requested_token:
                    raise DeliveryError('delivery job is already leased')
                if kind == self.LEASE_INVALID:
                    # A fresh claim must not paper over a trace nobody could
                    # explain: overwriting it would destroy the only record that
                    # an outcome was lost.
                    raise DeliveryError(f'DELIVERY_LEASE_INVALID: {detail}')
                if kind == self.LEASE_EXPIRED:
                    # Recovery must run first. poll_for_tab does it before
                    # offering work, but a direct event call would otherwise
                    # overwrite the expired trace and the lease term would stop
                    # being a server-side boundary.
                    self._latch_if_draining_reason(
                        job, f"claim over an expired lease: run={job.get('runId')} "
                             f"job={job.get('jobId')}")
                    raise DeliveryError(
                        'DELIVERY_LEASE_EXPIRED: recover the expired lease before claiming')

                job['claimLeaseToken'] = requested_token
                job['claimHeartbeatAt'] = now
                job['claimExpiresAt'] = utc_after(CLAIM_LEASE_SECONDS)
                job['claimedBy'] = {
                    'tabId': int(body.get('tabId')),
                    'url': str(body.get('url') or ''),
                    'at': now,
                    'leaseToken': requested_token,
                }
                return self.save_job(job)

            lease_token = str(body.get('leaseToken') or '').strip()
            self._touch_lease(job, lease_token)

            if event_type == 'RELEASE':
                self._clear_lease(job)
                return self.save_job(job)

            if event_type == 'CONVERSATION_BASELINE':
                marker = body.get('marker') if isinstance(body.get('marker'), dict) else {}
                if not isinstance(job.get('conversationBaseline'), dict) or not job.get('conversationBaseline'):
                    job['conversationBaseline'] = {
                        'rowCount': int(marker.get('rowCount') or 0),
                        'latestRowKey': str(marker.get('latestRowKey') or ''),
                        'latestPerfRow': str(marker.get('latestPerfRow') or ''),
                        'latestIndex': marker.get('latestIndex'),
                        'capturedAt': now,
                    }

            elif event_type == 'CONSUMED':
                marker = body.get('marker') if isinstance(body.get('marker'), dict) else {}
                job['status'] = 'CONSUMED'
                job['sendState'] = 'MANUAL_SENT'
                job['consumedAt'] = now
                job['consumedReason'] = str(body.get('reason') or 'MANUAL_SUBMIT_DETECTED')
                job['consumedMarker'] = marker
                self._clear_lease(job)
                return self.save_job(job)

            elif event_type == 'MESSAGE_STATE':
                job['messageState'] = str(body.get('state') or 'ERROR')
                job['messageError'] = body.get('error')
                if job['messageState'] == 'INSERTED':
                    job['messageInsertedAt'] = now

            elif event_type == 'SEND_STATE':
                job['sendState'] = str(body.get('state') or 'SEND_ERROR')
                job['sendError'] = body.get('error')
                if job['sendState'] == 'SENT':
                    job['sentAt'] = now
                    # The outcome is known, so the lease ends here, in the same
                    # save. The browser sends RELEASE afterwards, but by then
                    # the job is terminal and the early return ignores it — so
                    # a perfectly ordinary successful send used to leave an
                    # ACTIVE lease behind for ever, and the drain read that
                    # terminal job as quiet.
                    self._clear_lease(job)

            elif event_type == 'ATTACHMENT_STATE':
                attachment_id = str(body.get('attachmentId') or '')
                attachment = next(
                    (x for x in job.get('attachments') or [] if x.get('attachmentId') == attachment_id),
                    None
                )
                if attachment is None:
                    raise DeliveryError('attachment not found')

                new_state = str(body.get('state') or attachment.get('state') or 'ERROR')

                if new_state == 'RECOVER_PENDING':
                    recoveries = int(attachment.get('autoRecoveries') or 0) + 1
                    attachment['autoRecoveries'] = recoveries
                    if recoveries > MAX_AUTO_RECOVERIES:
                        new_state = 'STALLED'
                        body = dict(body)
                        body['phase'] = 'AUTO_RECOVER_LIMIT_REACHED'
                        body['error'] = (
                            str(body.get('error') or 'Automatic recovery requested')
                            + f'; automatic recovery limit reached ({MAX_AUTO_RECOVERIES})'
                        )

                attachment['state'] = new_state
                attachment['phase'] = str(body.get('phase') or new_state)

                if body.get('bytesFetched') is not None:
                    new_bytes = max(0, int(body.get('bytesFetched') or 0))
                    if new_bytes > int(attachment.get('bytesFetched') or 0):
                        attachment['lastProgressAt'] = now
                    attachment['bytesFetched'] = new_bytes

                if body.get('totalBytes') is not None:
                    attachment['totalBytes'] = max(0, int(body.get('totalBytes') or 0))

                if body.get('progressToken') is not None and body.get('progressToken') != attachment.get('progressToken'):
                    attachment['progressToken'] = body.get('progressToken')
                    attachment['lastProgressAt'] = now

                if new_state in {'FETCHING', 'CHAT_UPLOADING', 'CLAUDE_UPLOADING'} and not attachment.get('lastProgressAt'):
                    attachment['lastProgressAt'] = now

                if new_state in {'UPLOADED', 'ERROR', 'STALLED', 'RECOVER_PENDING'}:
                    attachment['finishedAt'] = now

                if new_state in {'FETCHING', 'CHAT_UPLOADING', 'CLAUDE_UPLOADING'} and attachment.get('startedAt') is None:
                    attachment['startedAt'] = now
                    attachment['attempts'] = int(attachment.get('attempts') or 0) + 1

                attachment['error'] = body.get('error')
                attachment['updatedAt'] = now

            elif event_type == 'HEARTBEAT':
                job['clientHeartbeatAt'] = now
                if body.get('clientPhase') is not None:
                    job['clientPhase'] = str(body.get('clientPhase') or '')
                if isinstance(body.get('busySignals'), list):
                    job['busySignals'] = [str(x) for x in body.get('busySignals')][:20]

            else:
                raise DeliveryError('unsupported delivery event')

            return self.save_job(job)

    def retry_failed(self, run_id: str, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(run_id, job_id)
            self._require_manifest(job)
            is_paused = str(job.get('status') or '') == PAUSED_JOB_STATE
            changed = 0

            for attachment in job.get('attachments') or []:
                if attachment.get('state') in RETRYABLE_ATTACHMENT_STATES:
                    attachment['state'] = 'RETRY_PENDING'
                    attachment['phase'] = 'WAITING_RETRY'
                    attachment['error'] = None
                    attachment['bytesFetched'] = 0
                    attachment['lastProgressAt'] = None
                    attachment['autoRecoveries'] = 0
                    attachment['updatedAt'] = utc_now()
                    changed += 1

            if changed == 0 and not is_paused:
                raise DeliveryError('no failed/stalled attachments to retry')

            if is_paused:
                job['status'] = 'QUEUED'
                job['pausedAt'] = None
                job['pauseReason'] = None
                job['dispatchEpoch'] = self.dispatch_epoch
                job['claimedBy'] = None
                job['clientHeartbeatAt'] = None
                job['claimLeaseToken'] = None
                job['claimHeartbeatAt'] = None
                job['claimExpiresAt'] = None

            job['sendState'] = 'NOT_REQUESTED'
            job['sendError'] = None
            return self.save_job(job)

    def request_send(self, run_id: str, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(run_id, job_id)
            self._require_manifest(job)
            bad = [x for x in job.get('attachments') or [] if x.get('state') != 'UPLOADED']
            if bad:
                raise DeliveryError('not all available attachments are uploaded')
            if job.get('messageState') != 'INSERTED':
                raise DeliveryError('message has not been inserted into the chat composer')
            job['sendState'] = 'SEND_REQUESTED'
            job['sendError'] = None
            return self.save_job(job)

    def attachment_chunk(self, run_id: str, job_id: str, attachment_id: str, offset: int, limit: int,
                         *, tab_id: int, lease_token: str, endpoint_id: str | None = None) -> dict[str, Any]:
        """Attachment bytes, to the tab that holds the lease and to nobody else.

        Both proofs are required arguments. They used to default to None and
        the empty string, with the whole check inside `if tab_id is not None`,
        so a caller that named neither was handed the bytes. The obligation
        held only because the single HTTP route happened to pass them — an
        obligation that depends on the caller getting it right is not one, and
        the next caller is where it stops holding.
        """
        job = self.get_job(run_id, job_id)
        self._require_target_tab(job, tab_id)
        self._require_target_endpoint(job, endpoint_id)
        self._require_manifest(job)
        # A live lease held by this caller. Reading bytes is work, and work
        # requires a claim — otherwise a drain that hands out no new jobs
        # still hands out new pieces of them.
        #
        # Validation only. This method does not save the job, so the mutating
        # helper it used to call renewed the lease in a dict that was then
        # dropped: an operation that looked like a heartbeat and kept nothing.
        # The client renews through HEARTBEAT, which is persisted.
        self._require_live_lease(job, lease_token)
        attachment = next((x for x in job.get('attachments') or [] if x.get('attachmentId') == attachment_id), None)
        if attachment is None:
            raise DeliveryError('attachment not found')
        path = Path(str(attachment.get('path') or '')).resolve()
        job_files = (self.job_dir(run_id, job_id) / 'files').resolve()
        if job_files not in path.parents or not path.is_file():
            raise DeliveryError('attachment file not found')
        total = path.stat().st_size
        offset = max(0, int(offset))
        limit = min(max(64 * 1024, int(limit or 512 * 1024)), 1024 * 1024)
        if offset > total:
            raise DeliveryError('offset beyond file size')
        with path.open('rb') as fh:
            fh.seek(offset)
            chunk = fh.read(limit)
        return {
            'ok': True,
            'attachmentId': attachment_id,
            'name': attachment.get('name'),
            'mimeType': attachment.get('mimeType') or 'application/octet-stream',
            'offset': offset,
            'bytes': len(chunk),
            'totalBytes': total,
            'eof': offset + len(chunk) >= total,
            'dataBase64': base64.b64encode(chunk).decode('ascii'),
        }

    def mark_stalled_jobs(self) -> list[dict[str, Any]]:
        now_dt = utc_now_dt()
        changed: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return changed

        with self.lock:
            for run_dir in self.data_dir.iterdir():
                if not run_dir.is_dir():
                    continue

                for job in self.list_jobs(run_dir.name):
                    if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                        continue
                    if str(job.get('dispatchEpoch') or '') != self.dispatch_epoch:
                        continue

                    timeout = max(30, int(job.get('stallTimeoutSeconds') or 120))
                    dirty = False
                    revoke_lease = False

                    for attachment in job.get('attachments') or []:
                        if attachment.get('state') not in ACTIVE_ATTACHMENT_STATES:
                            continue

                        dt = iso_dt(attachment.get('lastProgressAt') or attachment.get('startedAt'))
                        if dt is None or now_dt - dt <= timedelta(seconds=timeout):
                            continue

                        current_state = str(attachment.get('state') or '')
                        attachment['finishedAt'] = utc_now()
                        attachment['updatedAt'] = utc_now()

                        if current_state in {'CHAT_UPLOADING', 'CLAUDE_UPLOADING'}:
                            attachment['state'] = 'STALLED'
                            attachment['phase'] = 'CHAT_UPLOAD_NO_PROGRESS_NO_AUTO_RETRY'
                            attachment['error'] = (
                                f'No confirmed chat upload progress for {timeout} seconds. '
                                f'Automatic re-attach is disabled to prevent duplicates.'
                            )
                        else:
                            recoveries = int(attachment.get('autoRecoveries') or 0) + 1
                            attachment['autoRecoveries'] = recoveries

                            if recoveries <= MAX_AUTO_RECOVERIES:
                                attachment['state'] = 'RECOVER_PENDING'
                                attachment['phase'] = 'AUTO_RECOVER_FETCH_NO_PROGRESS'
                                attachment['error'] = (
                                    f'No delivery progress for {timeout} seconds; '
                                    f'automatic recovery {recoveries}/{MAX_AUTO_RECOVERIES}'
                                )
                            else:
                                attachment['state'] = 'STALLED'
                                attachment['phase'] = 'AUTO_RECOVER_LIMIT_REACHED'
                                attachment['error'] = (
                                    f'No delivery progress for {timeout} seconds; '
                                    f'automatic recovery limit reached ({MAX_AUTO_RECOVERIES})'
                                )

                        dirty = True
                        revoke_lease = True

                    if revoke_lease:
                        self._clear_lease(job)
                        job['leaseRecoveredAt'] = utc_now()

                    if dirty:
                        self.save_job(job)
                        changed.append(job)

        seen = {(str(x.get('runId') or ''), str(x.get('jobId') or '')) for x in changed}
        for job in self.recover_expired_leases():
            key = (str(job.get('runId') or ''), str(job.get('jobId') or ''))
            if key not in seen:
                changed.append(job)
                seen.add(key)

        return changed
