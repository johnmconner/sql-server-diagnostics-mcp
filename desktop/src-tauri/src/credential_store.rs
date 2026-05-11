use anyhow::{anyhow, Result};

pub const SECRET_NAMESPACE: &str = "sql-tshooter";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CredentialStatus {
    NotRequired,
    Ready,
    Missing,
    Unsupported,
}

impl CredentialStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::NotRequired => "notRequired",
            Self::Ready => "ready",
            Self::Missing => "missing",
            Self::Unsupported => "unsupported",
        }
    }
}

pub fn target_name(credential_ref: &str) -> Result<String> {
    let normalized = credential_ref.trim();
    if normalized.is_empty() {
        return Err(anyhow!("Profile field 'credentialRef' must not be empty."));
    }
    Ok(format!("{SECRET_NAMESPACE}/{normalized}"))
}

pub fn sql_password_status(credential_ref: Option<&str>) -> CredentialStatus {
    let Some(reference) = credential_ref
        .map(str::trim)
        .filter(|value| !value.is_empty())
    else {
        return CredentialStatus::Missing;
    };

    match read_password(reference) {
        Ok(_) => CredentialStatus::Ready,
        Err(_) if cfg!(windows) => CredentialStatus::Missing,
        Err(_) => CredentialStatus::Unsupported,
    }
}

#[cfg(not(windows))]
pub fn read_password(_credential_ref: &str) -> Result<String> {
    Err(anyhow!(
        "Profile credentialRef requires Windows Credential Manager and is only supported on Windows."
    ))
}

#[cfg(not(windows))]
pub fn write_password(_credential_ref: &str, _username: &str, _password: &str) -> Result<()> {
    Err(anyhow!(
        "Profile credentialRef requires Windows Credential Manager and is only supported on Windows."
    ))
}

#[cfg(windows)]
mod windows_impl {
    use super::target_name;
    use anyhow::{anyhow, Result};
    use std::ffi::OsStr;
    use std::iter;
    use std::os::windows::ffi::OsStrExt;
    use std::ptr::null_mut;
    use std::slice;
    use windows_sys::Win32::Security::Credentials::{
        CredFree, CredReadW, CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    pub fn read_password(credential_ref: &str) -> Result<String> {
        let target_name = target_name(credential_ref)?;
        let target = wide_string(&target_name);
        let mut credential_ptr: *mut CREDENTIALW = null_mut();

        unsafe {
            if CredReadW(target.as_ptr(), CRED_TYPE_GENERIC, 0, &mut credential_ptr) == 0 {
                return Err(last_os_error(&format!(
                    "Stored credential '{credential_ref}' was not found in Windows Credential Manager."
                )));
            }

            let result = read_credential_blob(credential_ptr);
            CredFree(credential_ptr.cast());
            result
        }
    }

    pub fn write_password(credential_ref: &str, username: &str, password: &str) -> Result<()> {
        let target_name = target_name(credential_ref)?;
        let target = wide_string(&target_name);
        let user = wide_string(username.trim());
        let mut password_utf16 = password.encode_utf16().collect::<Vec<_>>();

        let mut credential = CREDENTIALW {
            Flags: 0,
            Type: CRED_TYPE_GENERIC,
            TargetName: target.as_ptr().cast_mut(),
            Comment: null_mut(),
            LastWritten: Default::default(),
            CredentialBlobSize: (password_utf16.len() * std::mem::size_of::<u16>()) as u32,
            CredentialBlob: password_utf16.as_mut_ptr().cast(),
            Persist: CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount: 0,
            Attributes: null_mut(),
            TargetAlias: null_mut(),
            UserName: user.as_ptr().cast_mut(),
        };

        unsafe {
            if CredWriteW(&mut credential, 0) == 0 {
                return Err(last_os_error(
                    "Unable to save the credential to Windows Credential Manager.",
                ));
            }
        }

        Ok(())
    }

    fn read_credential_blob(credential_ptr: *mut CREDENTIALW) -> Result<String> {
        if credential_ptr.is_null() {
            return Err(anyhow!(
                "Unable to read stored credential from Windows Credential Manager."
            ));
        }

        let credential = unsafe { &*credential_ptr };
        if credential.CredentialBlobSize == 0 || credential.CredentialBlob.is_null() {
            return Err(anyhow!("Stored credential is empty."));
        }
        if credential.CredentialBlobSize % 2 != 0 {
            return Err(anyhow!("Stored credential payload is invalid UTF-16 data."));
        }

        let units = credential.CredentialBlobSize as usize / std::mem::size_of::<u16>();
        let slice =
            unsafe { slice::from_raw_parts(credential.CredentialBlob.cast::<u16>(), units) };
        String::from_utf16(slice)
            .map_err(|_| anyhow!("Stored credential payload is not valid UTF-16."))
    }

    fn last_os_error(default_message: &str) -> anyhow::Error {
        let os_error = std::io::Error::last_os_error();
        if os_error.raw_os_error().is_some() {
            anyhow!("{default_message} ({os_error})")
        } else {
            anyhow!(default_message.to_string())
        }
    }

    fn wide_string(value: &str) -> Vec<u16> {
        OsStr::new(value)
            .encode_wide()
            .chain(iter::once(0))
            .collect()
    }
}

#[cfg(windows)]
pub use windows_impl::{read_password, write_password};
