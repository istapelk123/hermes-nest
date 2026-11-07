"""Windows test process-tree containment. Live is Linux-only."""
import ctypes
import time
from ctypes import wintypes


class WindowsJob:
    def __init__(self, process):
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t),
                        ('maximum', ctypes.c_size_t), ('active', wintypes.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                        ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('read_ops', 'write_ops', 'other_ops',
                                                          'read_bytes', 'write_bytes', 'other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', ctypes.c_size_t),
                        ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t),
                        ('peak_job', ctypes.c_size_t)]
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.restype = ctypes.c_void_p
        self.k.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.k.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.k.CloseHandle.argtypes = [ctypes.c_void_p]
        self.handle = self.k.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (not self.handle or not self.k.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not self.k.AssignProcessToJobObject(self.handle, int(process._handle))):
            self.close()
            process.kill()
            process.wait()
            raise OSError('owned process job assignment failed')

    def close(self):
        if self.handle:
            self.k.TerminateJobObject.argtypes = [ctypes.c_void_p, wintypes.UINT]
            self.k.QueryInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.c_void_p]
            self.k.TerminateJobObject(self.handle, 1)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                accounting = ctypes.create_string_buffer(48)
                if not self.k.QueryInformationJobObject(self.handle, 1, accounting, 48, None):
                    break
                if ctypes.c_uint32.from_buffer(accounting, 40).value == 0:
                    break
                time.sleep(.01)
            self.k.CloseHandle(self.handle)
            self.handle = None
