#pragma once
// A crashing test executable must never open a Windows error box or the Just-In-Time debugger
// dialog on the owner's desktop: before main() runs, set the error mode src/main.cpp sets.
// Declared here instead of including <windows.h>, whose macros (far, near, min, max) break test code.
#ifdef _WIN32
extern "C" __declspec(dllimport) unsigned int __stdcall SetErrorMode(unsigned int mode);
extern "C" __declspec(dllimport) unsigned int __stdcall GetErrorMode();
namespace uzp_test_detail {
// SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX
inline const bool kNoErrorDialogs = (SetErrorMode(GetErrorMode() | 0x8003u), true);
}  // namespace uzp_test_detail
#endif
