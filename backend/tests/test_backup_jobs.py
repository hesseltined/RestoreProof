"""
Purpose: Unit tests for Proxmox backup-job VMID membership parsing.
Author: Doug Hesseltine
Created: 2026-07-30
Modified: 2026-07-30
Version: 1.0.0
"""

from app.services.proxmox import parse_backup_job_vmids, vmid_in_backup_jobs


def test_parse_vmid_list():
    covers_all, include, exclude = parse_backup_job_vmids(
        {"vmid": "100,101,133", "exclude": "101"}
    )
    assert covers_all is False
    assert include == {100, 101, 133}
    assert exclude == {101}


def test_parse_all_job():
    covers_all, include, exclude = parse_backup_job_vmids({"all": 1, "exclude": "200"})
    assert covers_all is True
    assert include == set()
    assert exclude == {200}


def test_vmid_in_listed_job():
    jobs = [
        {
            "id": "backup-weekly",
            "type": "vzdump",
            "enabled": 1,
            "schedule": "sun 01:00",
            "vmid": "100,133",
        }
    ]
    ok, matching = vmid_in_backup_jobs(133, jobs)
    assert ok is True
    assert matching[0]["id"] == "backup-weekly"
    ok2, _ = vmid_in_backup_jobs(112, jobs)
    assert ok2 is False


def test_vmid_excluded_from_all_job():
    jobs = [{"id": "all", "type": "vzdump", "enabled": 1, "all": 1, "exclude": "112"}]
    known = {100, 112, 133}
    ok, _ = vmid_in_backup_jobs(112, jobs, known_vmids=known)
    assert ok is False
    ok2, _ = vmid_in_backup_jobs(133, jobs, known_vmids=known)
    assert ok2 is True


def test_require_enabled_skips_disabled_jobs():
    jobs = [
        {
            "id": "backup-weekly",
            "type": "vzdump",
            "enabled": 0,
            "vmid": "133",
        }
    ]
    ok, matching = vmid_in_backup_jobs(133, jobs, require_enabled=False)
    assert ok is True
    assert matching
    ok2, matching2 = vmid_in_backup_jobs(133, jobs, require_enabled=True)
    assert ok2 is False
    assert matching2 == []
