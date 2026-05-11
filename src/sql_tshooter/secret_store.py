"""Windows credential store helpers for SQL TShooter profile secrets."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from sql_tshooter.errors import ConfigurationError


ERROR_NOT_FOUND = 1168
CRED_PERSIST_LOCAL_MACHINE = 2
CRED_TYPE_GENERIC = 1
SECRET_NAMESPACE = "sql-tshooter"


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def credential_target(credential_ref: str) -> str:
    normalized = credential_ref.strip()
    if not normalized:
        raise ConfigurationError("Profile field 'credentialRef' must not be empty.")
    return f"{SECRET_NAMESPACE}/{normalized}"


def is_windows() -> bool:
    return os.name == "nt"


def read_password(credential_ref: str) -> str:
    if not is_windows():
        raise ConfigurationError(
            "Profile credentialRef requires Windows Credential Manager and is only supported on Windows."
        )

    secret_bytes = _read_credential_blob(credential_target(credential_ref))
    if not secret_bytes:
        raise ConfigurationError(
            f"Stored credential '{credential_ref}' in Windows Credential Manager is empty."
        )
    return secret_bytes.decode("utf-16-le")


def has_password(credential_ref: str) -> bool:
    if not is_windows():
        return False
    try:
        secret_bytes = _read_credential_blob(credential_target(credential_ref))
    except ConfigurationError as exc:
        if "was not found" in str(exc):
            return False
        raise
    return bool(secret_bytes)


def _read_credential_blob(target_name: str) -> bytes:
    credential_ptr = ctypes.POINTER(CREDENTIALW)()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    ok = advapi32.CredReadW(target_name, CRED_TYPE_GENERIC, 0, ctypes.byref(credential_ptr))
    if not ok:
        error_code = ctypes.get_last_error()
        if error_code == ERROR_NOT_FOUND:
            raise ConfigurationError(
                f"Stored credential '{target_name.removeprefix(f'{SECRET_NAMESPACE}/')}' was not found in Windows Credential Manager."
            )
        raise ConfigurationError("Unable to read stored credential from Windows Credential Manager.")

    try:
        credential = credential_ptr.contents
        if credential.CredentialBlobSize == 0 or not credential.CredentialBlob:
            return b""
        return ctypes.string_at(
            credential.CredentialBlob,
            credential.CredentialBlobSize,
        )
    finally:
        advapi32.CredFree(credential_ptr)
