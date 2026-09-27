import platform
import sys

# CPython 3.12's _wmi.exec_query (behind platform.win32_ver/machine/processor)
# gives up on a slow WMI query after 1000/100 ms, but its worker thread keeps a
# pointer into the returned caller's stack and later CloseHandle()s whatever
# value sits there -- which can be the process thread pool's worker-factory
# handle (python/cpython#125315; the struct-copy fix only landed in 3.13).
# From then on two pool workers spin at 100% and no thread-pool callback ever
# runs: the first libtorrent session's network thread blocks forever in
# NotifyUnicastIpAddressChange, so SessionManager.__init__'s synchronous
# add_torrent() hangs with it (and QAudioOutput() crashes with 0xC000070A,
# MFShutdown() hangs at exit). The suite's only WMI queries come from
# `import PyInstaller` during collection, so a busy machine (slow WMI) was
# enough to hang it. Take the stdlib's own no-_wmi branch instead: platform
# falls back to sys.getwindowsversion() and `ver`.
if sys.version_info < (3, 13):

    def _wmi_query(*_keys):
        raise OSError("WMI disabled in tests (CPython 3.12 _wmi race)")

    platform._wmi_query = _wmi_query
