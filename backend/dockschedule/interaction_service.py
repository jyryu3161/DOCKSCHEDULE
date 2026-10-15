"""Bounded, on-demand pose analysis; no chemistry imports in the API process."""
import json
import logging
import os
import subprocess
import sys
from collections import OrderedDict
from threading import Lock


class AnalysisBusy(Exception):
    pass


_lock = Lock()
_cache = OrderedDict()
_CACHE_SIZE = 32


def _identity(path):
    stat = path.stat()
    return str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def pose_interactions(receptor, pose):
    # A single API process is used in deployment. Serialize previews and bound
    # waiting, memory, runtime and CPU use independently of docking workers.
    if not _lock.acquire(timeout=3):
        raise AnalysisBusy('다른 pose를 분석하고 있습니다. 잠시 후 다시 시도하세요.')
    try:
        key = _identity(receptor), _identity(pose)
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        env = dict(os.environ)
        env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   NUMEXPR_NUM_THREADS='1', OPENMM_CPU_THREADS='1', MPLBACKEND='Agg')
        try:
            process = subprocess.run(
                [sys.executable, '-m', 'dockschedule.interactions', str(receptor), str(pose)],
                env=env, capture_output=True, text=True, timeout=45,
            )
        except subprocess.TimeoutExpired:
            raise AnalysisBusy('상호작용 분석 시간 한도를 초과했습니다. 잠시 후 다시 시도하세요.') from None
        if process.returncode:
            logging.getLogger(__name__).warning('Pose analysis failed: %s', process.stderr[-2000:])
            raise ValueError('이 구조의 상호작용을 분석하지 못했습니다. 단백질의 수소·결합 정보와 pose SDF를 확인하세요.')
        result = json.loads(process.stdout)
        # Never return or cache a stale result after retry/deletion of the pose.
        if key != (_identity(receptor), _identity(pose)):
            raise AnalysisBusy('분석 중 pose가 변경되었습니다. 다시 분석해 주세요.')
        _cache[key] = result
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
        return result
    finally:
        _lock.release()
