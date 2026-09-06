#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
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
PAUSED_JOB_STATE = 'PAUSED_AFTER_RESTART'
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
                    )
                else:
                    dest = self._zip_one(src, files_dir, item['preferredName'])
                    add_attachment(
                        dest,
                        'report_packed',
                        str(item.get('originalPath') or ''),
                        item['preferredName'] + '.zip',
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
            add_attachment(aggregate, 'aggregate_archive', 'terminal log + non-archive reports', f'pap2-reports-{run_id}.tar.gz')
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
                'tabId': target_tab_id,
                'url': target_url,
                'chatType': target_chat_type,
                'chatLabel': target_chat_label,
            },
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
        saved = self.save_job(job)
        saved['supersededOlderJobs'] = self.supersede_older_jobs_for_tab(target_tab_id, run_id, job_id)
        return self.save_job(saved)

    @staticmethod
    def _same_page_url(left: str, right: str) -> bool:
        return str(left or '').split('#', 1)[0] == str(right or '').split('#', 1)[0]

    def _existing_recovery_replay(
        self,
        source_run_id: str,
        source_job_id: str,
        tab_id: int,
    ) -> dict[str, Any] | None:
        if not self.data_dir.is_dir():
            return None

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

                recovery_of = job.get('recoveryOf') if isinstance(job.get('recoveryOf'), dict) else {}
                if str(recovery_of.get('runId') or '') != str(source_run_id):
                    continue
                if str(recovery_of.get('jobId') or '') != str(source_job_id):
                    continue

                target = job.get('target') if isinstance(job.get('target'), dict) else {}
                if int(target.get('tabId') or -1) != int(tab_id):
                    continue

                if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                    continue

                if str(job.get('dispatchEpoch') or '') != self.dispatch_epoch:
                    continue

                return job

        return None

    @staticmethod
    def _job_submitted_at(job: dict[str, Any]) -> datetime | None:
        return (
            iso_dt(job.get('consumedAt'))
            or iso_dt(job.get('sentAt'))
            or iso_dt(job.get('updatedAt'))
            or iso_dt(job.get('createdAt'))
        )

    def find_latest_submitted_job(
        self,
        *,
        tab_id: int,
        page_url: str,
        max_age_seconds: int = 2 * 60 * 60,
    ) -> dict[str, Any] | None:
        """Find the most recently submitted PAP delivery for this exact tab/page."""
        candidates: list[tuple[datetime, dict[str, Any]]] = []

        if not self.data_dir.is_dir():
            return None

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

                job = self._load_json(job_file, {})
                if not isinstance(job, dict):
                    continue

                target = job.get('target') if isinstance(job.get('target'), dict) else {}
                if int(target.get('tabId') or -1) != int(tab_id):
                    continue

                target_url = str(target.get('url') or '')
                if target_url and page_url and not self._same_page_url(target_url, page_url):
                    continue

                status = str(job.get('status') or '')
                send_state = str(job.get('sendState') or '')
                submitted = (
                    status in {'CONSUMED', 'SENT'}
                    or send_state in {'MANUAL_SENT', 'SENT'}
                )
                if not submitted:
                    continue

                submitted_at = self._job_submitted_at(job)
                if submitted_at is None:
                    continue

                age = (current - submitted_at).total_seconds()
                if age < 0 or age > max_age_seconds:
                    continue

                candidates.append((submitted_at, job))

        if not candidates:
            return None

        candidates.sort(key=lambda row: row[0], reverse=True)
        return candidates[0][1]

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
                same_target = (
                    int(target.get('tabId') or -1) == int(tab_id)
                    and (
                        not str(target.get('url') or '')
                        or not page_url
                        or self._same_page_url(str(target.get('url') or ''), page_url)
                    )
                )
                if submitted and same_target:
                    explicit = candidate
            except DeliveryError:
                explicit = None

        latest = self.find_latest_submitted_job(
            tab_id=tab_id,
            page_url=page_url,
        )

        if explicit is None and latest is None:
            raise DeliveryError(
                'no submitted PAP delivery found for this chat tab/page'
            )

        if explicit is None:
            return latest, 'LATEST_SUBMITTED_SAME_TAB_PAGE'

        if latest is None:
            return explicit, 'BROWSER_SOURCE_REFERENCE'

        explicit_at = self._job_submitted_at(explicit)
        latest_at = self._job_submitted_at(latest)

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

            submitted_at = (
                iso_dt(source.get('consumedAt'))
                or iso_dt(source.get('sentAt'))
                or iso_dt(source.get('updatedAt'))
                or iso_dt(source.get('createdAt'))
            )
            if submitted_at is not None:
                age_seconds = (utc_now_dt() - submitted_at).total_seconds()
                if age_seconds > 2 * 60 * 60:
                    raise DeliveryError('recovery source is older than 2 hours')

            existing = self._existing_recovery_replay(
                source_run_id,
                source_job_id,
                tab_id,
            )
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
                        'tabId': int(tab_id),
                        'url': target_url or page_url,
                        'chatType': (source.get('target') or {}).get('chatType') if isinstance(source.get('target'), dict) else None,
                        'chatLabel': (source.get('target') or {}).get('chatLabel') if isinstance(source.get('target'), dict) else None,
                    },
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

    def supersede_older_jobs_for_tab(self, target_tab_id: int, keep_run_id: str, keep_job_id: str) -> int:
        changed = 0
        if not self.data_dir.is_dir():
            return changed
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
                target = job.get('target') if isinstance(job.get('target'), dict) else {}
                try:
                    same_tab = int(target.get('tabId') or -1) == int(target_tab_id)
                except Exception:
                    same_tab = False
                if not same_tab:
                    continue
                if str(job.get('status') or '') in TERMINAL_JOB_STATES:
                    continue
                job['status'] = 'SUPERSEDED'
                job['supersededAt'] = utc_now()
                job['supersededBy'] = {'runId': keep_run_id, 'jobId': keep_job_id}
                self.save_job(job)
                changed += 1
        return changed

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

    def _lease_is_active(self, job: dict[str, Any]) -> bool:
        token = str(job.get('claimLeaseToken') or '')
        expires = iso_dt(job.get('claimExpiresAt'))
        return bool(token and expires and expires > utc_now_dt())

    def _touch_lease(self, job: dict[str, Any], lease_token: str) -> None:
        if str(job.get('claimLeaseToken') or '') != str(lease_token or ''):
            raise DeliveryError('delivery lease token mismatch')
        expires = iso_dt(job.get('claimExpiresAt'))
        if expires is not None and expires <= utc_now_dt():
            raise DeliveryError('delivery lease expired')
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

                    token = str(job.get('claimLeaseToken') or '')
                    expires = iso_dt(job.get('claimExpiresAt'))
                    if not token or not expires or expires > now_dt:
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

                    self._clear_lease(job)
                    job['leaseRecoveredAt'] = utc_now()
                    self.save_job(job)
                    changed.append(job)

        return changed

    def poll_for_tab(self, tab_id: int, page_url: str) -> dict[str, Any] | None:
        self.recover_expired_leases()
        candidates: list[dict[str, Any]] = []
        if not self.data_dir.is_dir():
            return None
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
                target = job.get('target') if isinstance(job.get('target'), dict) else {}
                if int(target.get('tabId') or -1) != int(tab_id):
                    continue
                target_url = str(target.get('url') or '')
                if target_url and page_url and target_url.split('#', 1)[0] != page_url.split('#', 1)[0]:
                    continue
                if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                    continue
                if str(job.get('dispatchEpoch') or '') != self.dispatch_epoch:
                    continue
                if self._lease_is_active(job):
                    continue
                candidates.append(job)

        # The newest explicit Prepare wins. Old failed/stalled jobs must not
        # starve every later delivery job for the same browser tab.
        candidates.sort(key=lambda x: str(x.get('createdAt') or ''), reverse=True)
        return candidates[0] if candidates else None

    def update_from_client(self, run_id: str, job_id: str, body: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            job = self.get_job(run_id, job_id)

            if str(job.get('status') or '') in TERMINAL_JOB_STATES | {PAUSED_JOB_STATE}:
                return job

            target = job.get('target') if isinstance(job.get('target'), dict) else {}
            if int(body.get('tabId') or -1) != int(target.get('tabId') or -2):
                raise DeliveryError('wrong tabId for delivery job')

            event_type = str(body.get('event') or '')
            now = utc_now()

            if event_type == 'CLAIM':
                requested_token = str(body.get('leaseToken') or '').strip()
                if not requested_token:
                    raise DeliveryError('missing delivery lease token')

                current_token = str(job.get('claimLeaseToken') or '')
                if self._lease_is_active(job) and current_token != requested_token:
                    raise DeliveryError('delivery job is already leased')

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
            bad = [x for x in job.get('attachments') or [] if x.get('state') != 'UPLOADED']
            if bad:
                raise DeliveryError('not all available attachments are uploaded')
            if job.get('messageState') != 'INSERTED':
                raise DeliveryError('message has not been inserted into the chat composer')
            job['sendState'] = 'SEND_REQUESTED'
            job['sendError'] = None
            return self.save_job(job)

    def attachment_chunk(self, run_id: str, job_id: str, attachment_id: str, offset: int, limit: int) -> dict[str, Any]:
        job = self.get_job(run_id, job_id)
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
