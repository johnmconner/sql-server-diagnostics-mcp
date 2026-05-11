use anyhow::{anyhow, Context, Result};
use futures_util::{SinkExt, StreamExt};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Command as StdCommand, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_dialog::DialogExt;
use thiserror::Error;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{oneshot, Mutex, RwLock};
use tokio::time::{sleep, Duration};
use tokio_tungstenite::connect_async;
use tokio_tungstenite::tungstenite::Message;
use uuid::Uuid;

const MCP_SERVER_NAME: &str = "sql-tshooter";
const SNAPSHOT_EVENT: &str = "desktop://tab-snapshot";
const AUTO_APPROVED_SQL_TSHOOTER_TOOLS: &[&str] = &[
    "get_server_info",
    "get_top_waits",
    "get_active_requests",
    "get_blocking_sessions",
    "get_blocking_details",
    "get_expensive_queries",
    "get_lock_summary",
    "get_database_sizes",
    "get_connection_pressure",
    "get_session_pressure",
    "get_failed_jobs",
    "get_memory_status",
    "get_waiting_tasks",
    "get_disk_latency",
    "get_query_memory_grants",
    "get_query_store_top_queries",
    "get_query_store_regressions",
    "get_tempdb_usage",
    "get_wait_stats_by_query",
    "get_plan_cache_summary",
    "get_table_scan_summary",
    "get_worker_backlog",
    "get_database_hotspots",
    "get_query_plan_summary",
    "get_query_store_plan_variants",
    "get_query_store_query_detail",
];

#[derive(Debug, Error)]
enum DesktopError {
    #[error("{0}")]
    Message(String),
}

impl From<anyhow::Error> for DesktopError {
    fn from(value: anyhow::Error) -> Self {
        Self::Message(value.to_string())
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProfileSummary {
    id: String,
    label: String,
    host: String,
    default_database: Option<String>,
    databases: Vec<String>,
    auth_mode: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct RestoredTarget {
    tab_id: String,
    profile_id: String,
    database: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct BootstrapPayload {
    profile_file: String,
    workspace_root: String,
    profiles: Vec<ProfileSummary>,
    restored_targets: Vec<RestoredTarget>,
    profile_load_error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct TranscriptEntry {
    id: String,
    kind: String,
    title: Option<String>,
    text: Option<String>,
    status: Option<String>,
    metadata: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PendingApproval {
    request_id: String,
    method: String,
    title: String,
    details: Option<String>,
    request: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct TabSnapshot {
    id: String,
    target_key: String,
    profile_id: String,
    profile_label: String,
    database: String,
    thread_id: Option<String>,
    codex_status: String,
    auth_method: Option<String>,
    mcp_status: Option<String>,
    active_turn_id: Option<String>,
    last_error: Option<String>,
    entries: Vec<TranscriptEntry>,
    pending_approvals: Vec<PendingApproval>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PersistedTargetState {
    target_key: String,
    tab_id: String,
    profile_id: String,
    database: String,
    thread_id: Option<String>,
    restore_on_launch: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
#[serde(rename_all = "camelCase")]
struct PersistedAppState {
    profile_file: Option<String>,
    targets: Vec<PersistedTargetState>,
}

#[derive(Debug, Clone, Deserialize)]
struct ProfileFile {
    profiles: Vec<ProfileDefinition>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ProfileDefinition {
    id: String,
    label: Option<String>,
    host: String,
    port: Option<u16>,
    auth_mode: Option<String>,
    username: Option<String>,
    password: Option<String>,
    database: Option<String>,
    databases: Option<Vec<String>>,
    driver: Option<String>,
    encrypt: Option<bool>,
    trust_server_certificate: Option<bool>,
    connection_timeout_seconds: Option<u32>,
    query_timeout_seconds: Option<u32>,
    log_path: Option<String>,
    max_logged_tool_output_chars: Option<u32>,
}

impl ProfileDefinition {
    fn summary(&self) -> ProfileSummary {
        ProfileSummary {
            id: self.id.clone(),
            label: self.label.clone().unwrap_or_else(|| self.id.clone()),
            host: self.host.clone(),
            default_database: self.database.clone(),
            databases: self.database_list(),
            auth_mode: self.auth_mode.clone().unwrap_or_else(|| "sql".to_string()),
        }
    }

    fn database_list(&self) -> Vec<String> {
        let mut databases = self.databases.clone().unwrap_or_default();
        if let Some(default_database) = &self.database {
            if !databases.iter().any(|item| item == default_database) {
                databases.push(default_database.clone());
            }
        }
        if databases.is_empty() {
            databases.push("master".to_string());
        }
        databases
    }
}

#[derive(Debug, Clone)]
struct CommandSpec {
    program: String,
    args: Vec<String>,
}

impl CommandSpec {
    fn from_parts(program: &str, args: &[&str]) -> Self {
        Self {
            program: program.to_string(),
            args: args.iter().map(|item| item.to_string()).collect(),
        }
    }

    fn with_tail(&self, tail: &[String]) -> Vec<String> {
        let mut combined = self.args.clone();
        combined.extend(tail.iter().cloned());
        combined
    }
}

#[derive(Debug, Clone)]
struct ResolvedConfig {
    default_profile_file: PathBuf,
    profile_file_locked: bool,
    workspace_root: PathBuf,
    state_file: PathBuf,
    codex_command: CommandSpec,
    python_command: CommandSpec,
}

#[derive(Debug, Clone)]
struct PendingServerRequest {
    id: Value,
    method: String,
    params: Value,
}

type WsStream =
    tokio_tungstenite::WebSocketStream<tokio_tungstenite::MaybeTlsStream<tokio::net::TcpStream>>;
type WsWriter = futures_util::stream::SplitSink<WsStream, Message>;

struct JsonRpcClient {
    writer: Arc<Mutex<WsWriter>>,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, DesktopError>>>>>,
    next_id: AtomicU64,
}

impl JsonRpcClient {
    fn new(writer: WsWriter) -> Self {
        Self {
            writer: Arc::new(Mutex::new(writer)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(1),
        }
    }

    async fn request(&self, method: &str, params: Value) -> Result<Value, DesktopError> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let id_value = json!(id);
        let request_key = request_key(&id_value);
        let payload = json!({
            "jsonrpc": "2.0",
            "id": id,
            "method": method,
            "params": params,
        });

        let (sender, receiver) = oneshot::channel();
        self.pending.lock().await.insert(request_key, sender);
        self.send_message(payload).await?;

        receiver
            .await
            .map_err(|_| DesktopError::Message("RPC response channel closed.".to_string()))?
    }

    async fn notify(&self, method: &str, params: Value) -> Result<(), DesktopError> {
        let payload = json!({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        });
        self.send_message(payload).await
    }

    async fn respond_result(&self, id: Value, result: Value) -> Result<(), DesktopError> {
        let payload = json!({
            "jsonrpc": "2.0",
            "id": id,
            "result": result,
        });
        self.send_message(payload).await
    }

    async fn respond_error(&self, id: Value, code: i64, message: &str) -> Result<(), DesktopError> {
        let payload = json!({
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": code,
                "message": message,
            },
        });
        self.send_message(payload).await
    }

    async fn send_message(&self, payload: Value) -> Result<(), DesktopError> {
        let mut writer = self.writer.lock().await;
        writer
            .send(Message::Text(payload.to_string()))
            .await
            .map_err(|error| {
                DesktopError::Message(format!("Unable to send app-server message: {error}"))
            })
    }
}

struct TabSession {
    snapshot: RwLock<TabSnapshot>,
    rpc: Arc<JsonRpcClient>,
    process: Mutex<Option<Child>>,
    pending_requests: Mutex<HashMap<String, PendingServerRequest>>,
    mcp_log_path: PathBuf,
}

struct DesktopState {
    app_handle: AppHandle,
    config: ResolvedConfig,
    profile_file: RwLock<PathBuf>,
    sessions: Mutex<HashMap<String, Arc<TabSession>>>,
    saved_targets: Mutex<HashMap<String, PersistedTargetState>>,
}

impl DesktopState {
    fn initialize(app_handle: AppHandle) -> Result<Self> {
        let config = resolve_runtime_config()?;
        let persisted_state = load_saved_state(&config.state_file)?;
        let profile_file = if config.profile_file_locked {
            config.default_profile_file.clone()
        } else {
            let preferred = persisted_state
                .profile_file
                .as_deref()
                .map(PathBuf::from)
                .unwrap_or_else(|| config.default_profile_file.clone());
            if preferred.exists() {
                preferred
            } else {
                let legacy = legacy_profile_file();
                if legacy.exists() {
                    legacy
                } else {
                    preferred
                }
            }
        };
        Ok(Self {
            app_handle,
            config,
            profile_file: RwLock::new(profile_file),
            sessions: Mutex::new(HashMap::new()),
            saved_targets: Mutex::new(
                persisted_state
                    .targets
                    .into_iter()
                    .map(|target| (target.target_key.clone(), target))
                    .collect(),
            ),
        })
    }

    async fn current_profile_file(&self) -> PathBuf {
        self.profile_file.read().await.clone()
    }

    async fn set_profile_file(&self, profile_file: PathBuf) -> Result<()> {
        *self.profile_file.write().await = profile_file;
        self.persist_state().await
    }

    async fn persist_state(&self) -> Result<()> {
        let map = self.saved_targets.lock().await;
        let payload = PersistedAppState {
            profile_file: Some(self.profile_file.read().await.display().to_string()),
            targets: map.values().cloned().collect(),
        };

        if let Some(parent) = self.config.state_file.parent() {
            std::fs::create_dir_all(parent)
                .with_context(|| format!("Unable to create {}", parent.display()))?;
        }

        std::fs::write(
            &self.config.state_file,
            serde_json::to_vec_pretty(&payload)?,
        )
        .with_context(|| format!("Unable to write {}", self.config.state_file.display()))?;

        Ok(())
    }
}

#[derive(Clone, Copy, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
enum ApprovalAction {
    Accept,
    AcceptForSession,
    Decline,
    Cancel,
    AcceptPermissionsForTurn,
    AcceptPermissionsForSession,
    SubmitAnswers,
}

#[tauri::command]
async fn bootstrap_app(
    state: State<'_, DesktopState>,
) -> std::result::Result<BootstrapPayload, String> {
    build_bootstrap_payload(&state).await
}

#[tauri::command]
async fn open_target_tab(
    profile_id: String,
    database: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let profile_file = state.current_profile_file().await;
    let profiles = load_or_create_profiles(&profile_file).map_err(|error| error.to_string())?;
    let profile = profiles
        .into_iter()
        .find(|profile| profile.id == profile_id)
        .ok_or_else(|| format!("Unknown profile '{profile_id}'."))?;

    let chosen_database = if database.trim().is_empty() {
        profile
            .database
            .clone()
            .or_else(|| profile.database_list().into_iter().next())
            .unwrap_or_else(|| "master".to_string())
    } else {
        database.trim().to_string()
    };

    let target_key = format!("{}::{chosen_database}", profile.id);

    let sessions = {
        let sessions = state.sessions.lock().await;
        sessions.values().cloned().collect::<Vec<_>>()
    };
    for existing in sessions {
        if existing.snapshot.read().await.target_key == target_key {
            return Ok(existing.snapshot.read().await.clone());
        }
    }

    let saved_target = {
        let saved = state.saved_targets.lock().await;
        saved.get(&target_key).cloned()
    };

    let tab_id = saved_target
        .as_ref()
        .map(|item| item.tab_id.clone())
        .unwrap_or_else(|| Uuid::new_v4().to_string());

    let initial_snapshot = TabSnapshot {
        id: tab_id.clone(),
        target_key: target_key.clone(),
        profile_id: profile.id.clone(),
        profile_label: profile.label.clone().unwrap_or_else(|| profile.id.clone()),
        database: chosen_database.clone(),
        thread_id: saved_target
            .as_ref()
            .and_then(|item| item.thread_id.clone()),
        codex_status: "connecting".to_string(),
        auth_method: None,
        mcp_status: Some("starting".to_string()),
        active_turn_id: None,
        last_error: None,
        entries: Vec::new(),
        pending_approvals: Vec::new(),
    };

    let port = allocate_port().map_err(|error| error.to_string())?;
    let listen_url = format!("ws://127.0.0.1:{port}");
    let mut child = build_codex_child(
        &state.config,
        &profile_file,
        &profile,
        &chosen_database,
        &listen_url,
    )
    .map_err(|error| error.to_string())?;

    let stderr = child.stderr.take();
    let socket = connect_with_retry(&listen_url)
        .await
        .map_err(|error| error.to_string())?;
    let (writer, reader) = socket.split();

    let rpc = Arc::new(JsonRpcClient::new(writer));
    let session = Arc::new(TabSession {
        snapshot: RwLock::new(initial_snapshot),
        rpc: rpc.clone(),
        process: Mutex::new(Some(child)),
        pending_requests: Mutex::new(HashMap::new()),
        mcp_log_path: resolve_mcp_log_path(&state.config.workspace_root, profile.log_path.as_deref()),
    });

    state
        .sessions
        .lock()
        .await
        .insert(tab_id.clone(), session.clone());

    emit_snapshot(&state.app_handle, &session).await;

    if let Some(stderr) = stderr {
        let session_for_stderr = session.clone();
        let app_for_stderr = state.app_handle.clone();
        tauri::async_runtime::spawn(async move {
            read_process_stderr(app_for_stderr, session_for_stderr, stderr).await;
        });
    }

    let app_for_reader = state.app_handle.clone();
    let session_for_reader = session.clone();
    let rpc_for_reader = rpc.clone();
    tauri::async_runtime::spawn(async move {
        process_socket_messages(app_for_reader, session_for_reader, rpc_for_reader, reader).await;
    });

    initialize_client(&rpc)
        .await
        .map_err(|error| error.to_string())?;
    apply_auth_status(&session, &rpc).await;
    apply_mcp_status(&session, &rpc).await;

    let thread_id = restore_or_start_thread(
        &state,
        &session,
        &profile,
        &chosen_database,
        saved_target
            .as_ref()
            .and_then(|item| item.thread_id.clone()),
    )
    .await
    .map_err(|error| error.to_string())?;

    {
        let mut saved = state.saved_targets.lock().await;
        saved.insert(
            target_key,
            PersistedTargetState {
                target_key: format!("{}::{chosen_database}", profile.id),
                tab_id: tab_id.clone(),
                profile_id: profile.id.clone(),
                database: chosen_database.clone(),
                thread_id: Some(thread_id),
                restore_on_launch: true,
            },
        );
    }
    state
        .persist_state()
        .await
        .map_err(|error| error.to_string())?;

    let snapshot = session.snapshot.read().await.clone();
    Ok(snapshot)
}

#[tauri::command]
async fn set_profile_file(
    profile_file: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<BootstrapPayload, String> {
    let trimmed = profile_file.trim();
    if trimmed.is_empty() {
        return Err("Profile file path cannot be empty.".to_string());
    }

    state
        .set_profile_file(PathBuf::from(trimmed))
        .await
        .map_err(|error| error.to_string())?;
    build_bootstrap_payload(&state).await
}

#[tauri::command]
async fn pick_profile_file(
    app: AppHandle,
    state: State<'_, DesktopState>,
) -> std::result::Result<Option<BootstrapPayload>, String> {
    let selected = app
        .dialog()
        .file()
        .add_filter("JSON", &["json"])
        .blocking_pick_file();

    let Some(selected) = selected else {
        return Ok(None);
    };

    let selected_path = selected
        .into_path()
        .map_err(|error| format!("Unable to use the selected file path: {error}"))?;

    state
        .set_profile_file(selected_path)
        .await
        .map_err(|error| error.to_string())?;

    build_bootstrap_payload(&state).await.map(Some)
}

#[tauri::command]
async fn get_tab_snapshot(
    tab_id: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let session = {
        let sessions = state.sessions.lock().await;
        sessions
            .get(&tab_id)
            .cloned()
            .ok_or_else(|| format!("Unknown tab '{tab_id}'."))?
    };
    let snapshot = session.snapshot.read().await.clone();
    Ok(snapshot)
}

#[tauri::command]
async fn send_prompt(
    tab_id: String,
    text: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let session = get_session(&state, &tab_id).await?;
    let thread_id = session
        .snapshot
        .read()
        .await
        .thread_id
        .clone()
        .ok_or_else(|| "Tab has no active thread.".to_string())?;

    let response = session
        .rpc
        .request(
            "turn/start",
            json!({
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": text,
                        "text_elements": [],
                    }
                ],
            }),
        )
        .await
        .map_err(|error| error.to_string())?;

    if let Some(turn) = response.get("turn") {
        {
            let mut snapshot = session.snapshot.write().await;
            snapshot.active_turn_id = turn
                .get("id")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            snapshot.codex_status = "running".to_string();
            merge_turn_items(&mut snapshot.entries, turn);
        }
        emit_snapshot(&state.app_handle, &session).await;
    }

    let snapshot = session.snapshot.read().await.clone();
    Ok(snapshot)
}

#[tauri::command]
async fn interrupt_turn(
    tab_id: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let session = get_session(&state, &tab_id).await?;
    let snapshot = session.snapshot.read().await.clone();
    let thread_id = snapshot
        .thread_id
        .ok_or_else(|| "Tab has no active thread.".to_string())?;
    let turn_id = snapshot
        .active_turn_id
        .ok_or_else(|| "Tab has no active turn.".to_string())?;

    session
        .rpc
        .request(
            "turn/interrupt",
            json!({
                "threadId": thread_id,
                "turnId": turn_id,
            }),
        )
        .await
        .map_err(|error| error.to_string())?;

    {
        let mut snapshot = session.snapshot.write().await;
        snapshot.codex_status = "interrupting".to_string();
    }
    emit_snapshot(&state.app_handle, &session).await;
    let snapshot = session.snapshot.read().await.clone();
    Ok(snapshot)
}

#[tauri::command]
async fn clear_target_conversation(
    tab_id: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let session = get_session(&state, &tab_id).await?;
    let snapshot = session.snapshot.read().await.clone();

    if snapshot.active_turn_id.is_some() {
        return Err("Interrupt the active turn before clearing the conversation.".to_string());
    }

    let profile_file = state.current_profile_file().await;
    let profiles = load_or_create_profiles(&profile_file).map_err(|error| error.to_string())?;
    let profile = profiles
        .into_iter()
        .find(|profile| profile.id == snapshot.profile_id)
        .ok_or_else(|| format!("Unknown profile '{}'.", snapshot.profile_id))?;

    let thread_id = restore_or_start_thread(
        &state,
        &session,
        &profile,
        &snapshot.database,
        None,
    )
    .await
    .map_err(|error| error.to_string())?;

    {
        let mut session_snapshot = session.snapshot.write().await;
        session_snapshot.thread_id = Some(thread_id.clone());
        session_snapshot.codex_status = "ready".to_string();
        session_snapshot.active_turn_id = None;
        session_snapshot.last_error = None;
        session_snapshot.entries.clear();
        session_snapshot.pending_approvals.clear();
    }

    session.pending_requests.lock().await.clear();

    {
        let mut saved = state.saved_targets.lock().await;
        if let Some(target) = saved.get_mut(&snapshot.target_key) {
            target.thread_id = Some(thread_id);
        }
    }
    state
        .persist_state()
        .await
        .map_err(|error| error.to_string())?;

    emit_snapshot(&state.app_handle, &session).await;
    let updated_snapshot = session.snapshot.read().await.clone();
    Ok(updated_snapshot)
}

#[tauri::command]
async fn respond_to_approval(
    tab_id: String,
    request_id: String,
    action: ApprovalAction,
    answers: Option<HashMap<String, String>>,
    state: State<'_, DesktopState>,
) -> std::result::Result<TabSnapshot, String> {
    let session = get_session(&state, &tab_id).await?;
    let pending = {
        let requests = session.pending_requests.lock().await;
        requests.get(&request_id).cloned()
    }
    .ok_or_else(|| format!("Unknown approval request '{request_id}'."))?;

    match pending.method.as_str() {
        "item/commandExecution/requestApproval" | "item/fileChange/requestApproval" => {
            respond_with_standard_decision(&session, pending.id, action).await?;
        }
        "item/permissions/requestApproval" => match action {
            ApprovalAction::AcceptPermissionsForTurn
            | ApprovalAction::AcceptPermissionsForSession => {
                let permissions = pending
                    .params
                    .get("permissions")
                    .cloned()
                    .unwrap_or_else(|| json!({}));
                let scope = if matches!(action, ApprovalAction::AcceptPermissionsForSession) {
                    "session"
                } else {
                    "turn"
                };

                session
                    .rpc
                    .respond_result(
                        pending.id,
                        json!({
                            "permissions": permissions,
                            "scope": scope,
                        }),
                    )
                    .await
                    .map_err(|error| error.to_string())?;
            }
            ApprovalAction::Decline | ApprovalAction::Cancel => {
                session
                    .rpc
                    .respond_error(pending.id, 4001, "User declined the permission request.")
                    .await
                    .map_err(|error| error.to_string())?;
            }
            _ => return Err("Unsupported permission approval action.".to_string()),
        },
        "item/tool/requestUserInput" => match action {
            ApprovalAction::Accept
            | ApprovalAction::AcceptForSession
            | ApprovalAction::SubmitAnswers => {
                respond_with_elicitation(&session, pending.id, "accept", answers).await?;
            }
            ApprovalAction::Decline | ApprovalAction::Cancel => {
                let action_name = if matches!(action, ApprovalAction::Decline) {
                    "decline"
                } else {
                    "cancel"
                };
                respond_with_elicitation(&session, pending.id, action_name, None).await?;
            }
            _ => return Err("Unsupported tool-input action.".to_string()),
        },
        method if is_elicitation_request(method, &pending.params) => match action {
            ApprovalAction::Accept
            | ApprovalAction::AcceptForSession
            | ApprovalAction::SubmitAnswers => {
                respond_with_elicitation(&session, pending.id, "accept", answers).await?;
            }
            ApprovalAction::Decline => {
                respond_with_elicitation(&session, pending.id, "decline", None).await?;
            }
            ApprovalAction::Cancel => {
                respond_with_elicitation(&session, pending.id, "cancel", None).await?;
            }
            _ => return Err("Unsupported elicitation action.".to_string()),
        },
        _ => match action {
            ApprovalAction::Accept
            | ApprovalAction::AcceptForSession
            | ApprovalAction::Decline
            | ApprovalAction::Cancel => {
                // Default to decision-based handling for newer approval methods.
                respond_with_standard_decision(&session, pending.id, action).await?;
            }
            _ => {
                return Err(format!(
                    "Unsupported approval method '{}'.",
                    pending.method
                ));
            }
        },
    }

    {
        let mut requests = session.pending_requests.lock().await;
        requests.remove(&request_id);
    }

    {
        let mut snapshot = session.snapshot.write().await;
        snapshot.pending_approvals = collect_pending_approvals(&session).await;
    }
    emit_snapshot(&state.app_handle, &session).await;

    let snapshot = session.snapshot.read().await.clone();
    Ok(snapshot)
}

async fn respond_with_standard_decision(
    session: &Arc<TabSession>,
    id: Value,
    action: ApprovalAction,
) -> std::result::Result<(), String> {
    let decision = match action {
        ApprovalAction::Accept => json!("accept"),
        ApprovalAction::AcceptForSession => json!("acceptForSession"),
        ApprovalAction::Decline => json!("decline"),
        ApprovalAction::Cancel => json!("cancel"),
        _ => {
            return Err("Unsupported approval action for decision-based request.".to_string());
        }
    };

    session
        .rpc
        .respond_result(
            id,
            json!({
                "decision": decision,
            }),
        )
        .await
        .map_err(|error| error.to_string())
}

async fn respond_with_elicitation(
    session: &Arc<TabSession>,
    id: Value,
    action: &str,
    answers: Option<HashMap<String, String>>,
) -> std::result::Result<(), String> {
    let mut result = json!({
        "action": action,
    });

    if action == "accept" {
        let content = answers
            .map(serde_json::to_value)
            .transpose()
            .map_err(|error| error.to_string())?
            .unwrap_or_else(|| json!({}));
        result["content"] = content;
    }

    session
        .rpc
        .respond_result(id, result)
        .await
        .map_err(|error| error.to_string())
}

fn is_elicitation_request(method: &str, params: &Value) -> bool {
    method.contains("elicit")
        || method.contains("elicitation")
        || params.get("requestedSchema").is_some()
        || params.get("questions").is_some()
}

#[tauri::command]
async fn close_target_tab(
    tab_id: String,
    state: State<'_, DesktopState>,
) -> std::result::Result<(), String> {
    let session = {
        let mut sessions = state.sessions.lock().await;
        sessions.remove(&tab_id)
    }
    .ok_or_else(|| format!("Unknown tab '{tab_id}'."))?;

    if let Some(mut child) = session.process.lock().await.take() {
        let _ = child.kill().await;
    }

    {
        let mut saved = state.saved_targets.lock().await;
        for target in saved.values_mut() {
            if target.tab_id == tab_id {
                target.restore_on_launch = false;
            }
        }
    }
    state
        .persist_state()
        .await
        .map_err(|error| error.to_string())?;
    Ok(())
}

fn load_profiles(path: &Path) -> Result<Vec<ProfileDefinition>> {
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("Unable to read profile file '{}'.", path.display()))?;
    let parsed: ProfileFile = serde_json::from_str(&raw)
        .with_context(|| format!("Profile file '{}' is not valid JSON.", path.display()))?;
    if parsed.profiles.is_empty() {
        return Err(anyhow!(
            "Profile file '{}' does not define any profiles.",
            path.display()
        ));
    }
    Ok(parsed.profiles)
}

fn load_or_create_profiles(path: &Path) -> Result<Vec<ProfileDefinition>> {
    ensure_placeholder_profile_file(path)?;
    load_profiles(path)
}

fn ensure_placeholder_profile_file(path: &Path) -> Result<()> {
    if path.exists() {
        return Ok(());
    }

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .with_context(|| format!("Unable to create {}", parent.display()))?;
    }

    std::fs::write(
        path,
        placeholder_profile_json(path.file_stem().and_then(|name| name.to_str())),
    )
    .with_context(|| {
        format!(
            "Unable to write placeholder profile file '{}'.",
            path.display()
        )
    })
}

fn placeholder_profile_json(seed: Option<&str>) -> Vec<u8> {
    let id = seed
        .map(|value| value.trim())
        .filter(|value| !value.is_empty())
        .unwrap_or("sample-sql");

    serde_json::to_vec_pretty(&json!({
        "profiles": [
            {
                "id": id,
                "label": "Sample SQL Server",
                "host": "localhost",
                "port": 1433,
                "authMode": "sql",
                "username": "readonly_user",
                "password": "change-me",
                "database": "master",
                "databases": ["master"],
                "driver": "ODBC Driver 18 for SQL Server",
                "encrypt": true,
                "trustServerCertificate": true,
                "connectionTimeoutSeconds": 10,
                "queryTimeoutSeconds": 30,
                "maxLoggedToolOutputChars": 12000
            }
        ]
    }))
    .expect("placeholder profile JSON must serialize")
}

fn load_saved_state(path: &Path) -> Result<PersistedAppState> {
    if !path.exists() {
        return Ok(PersistedAppState::default());
    }
    let raw = std::fs::read_to_string(path)
        .with_context(|| format!("Unable to read state file '{}'.", path.display()))?;
    let parsed: PersistedAppState = serde_json::from_str(&raw)
        .with_context(|| format!("State file '{}' is not valid JSON.", path.display()))?;
    Ok(parsed)
}

fn resolve_runtime_config() -> Result<ResolvedConfig> {
    let workspace_root = resolve_workspace_root()?;
    let (default_profile_file, profile_file_locked) = resolve_profile_file(&workspace_root);
    let state_file = resolve_state_file()?;
    let codex_command = resolve_available_command(
        env::var("CODEX_COMMAND").ok(),
        &[CommandSpec::from_parts("codex", &[])],
        "--version",
    )?;
    let python_command = resolve_available_command(
        env::var("SQL_TSHOOTER_PYTHON_COMMAND").ok(),
        &[
            CommandSpec::from_parts("python3", &[]),
            CommandSpec::from_parts("python", &[]),
            CommandSpec::from_parts("py", &["-3"]),
        ],
        "--version",
    )?;

    Ok(ResolvedConfig {
        default_profile_file,
        profile_file_locked,
        workspace_root,
        state_file,
        codex_command,
        python_command,
    })
}

fn resolve_profile_file(workspace_root: &Path) -> (PathBuf, bool) {
    if let Ok(path) = env::var("SQL_TSHOOTER_PROFILE_FILE") {
        if !path.trim().is_empty() {
            return (PathBuf::from(path), true);
        }
    }

    let workspace_profile = workspace_root.join("profiles.json");
    if workspace_profile.exists() || workspace_root.join("pyproject.toml").exists() {
        return (workspace_profile, false);
    }

    let root = dirs::config_dir().unwrap_or_else(|| {
        dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".config")
    });

    (root.join("sql-tshooter").join("profiles.json"), false)
}

async fn build_bootstrap_payload(
    state: &DesktopState,
) -> std::result::Result<BootstrapPayload, String> {
    let profile_file = state.current_profile_file().await;
    let (profiles, profile_load_error) = match load_or_create_profiles(&profile_file) {
        Ok(loaded) => (
            loaded
                .into_iter()
                .map(|profile| profile.summary())
                .collect::<Vec<_>>(),
            None,
        ),
        Err(error) => (Vec::new(), Some(error.to_string())),
    };

    let restored_targets = {
        let saved = state.saved_targets.lock().await;
        saved
            .values()
            .filter(|target| {
                target.restore_on_launch
                    && profiles
                        .iter()
                        .any(|profile| profile.id == target.profile_id)
            })
            .map(|target| RestoredTarget {
                tab_id: target.tab_id.clone(),
                profile_id: target.profile_id.clone(),
                database: target.database.clone(),
            })
            .collect::<Vec<_>>()
    };

    Ok(BootstrapPayload {
        profile_file: profile_file.display().to_string(),
        workspace_root: state.config.workspace_root.display().to_string(),
        profiles,
        restored_targets,
        profile_load_error,
    })
}

fn default_profile_file_root() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".sql-tshooter")
}

fn legacy_profile_file() -> PathBuf {
    default_profile_file_root().join("profiles.json")
}

fn resolve_state_file() -> Result<PathBuf> {
    let root = dirs::config_dir().unwrap_or_else(|| {
        dirs::home_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join(".config")
    });
    Ok(root.join("sql-tshooter-desktop").join("state.json"))
}

fn resolve_workspace_root() -> Result<PathBuf> {
    if let Ok(path) = env::var("SQL_TSHOOTER_WORKSPACE_ROOT") {
        if !path.trim().is_empty() {
            return Ok(PathBuf::from(path));
        }
    }

    let current_dir = env::current_dir().context("Unable to resolve the current directory.")?;
    if current_dir.join("pyproject.toml").exists() {
        return Ok(current_dir);
    }

    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    if let Some(repo_root) = manifest_dir.parent().and_then(|path| path.parent()) {
        if repo_root.join("pyproject.toml").exists() {
            return Ok(repo_root.to_path_buf());
        }
    }

    Ok(current_dir)
}

fn resolve_available_command(
    override_value: Option<String>,
    defaults: &[CommandSpec],
    probe_arg: &str,
) -> Result<CommandSpec> {
    let mut candidates = Vec::new();
    if let Some(override_value) = override_value {
        let mut parts = override_value
            .split_whitespace()
            .map(ToString::to_string)
            .collect::<Vec<_>>();
        if !parts.is_empty() {
            let program = parts.remove(0);
            candidates.push(CommandSpec {
                program,
                args: parts,
            });
        }
    }
    candidates.extend_from_slice(defaults);

    for candidate in expand_command_candidates(candidates) {
        if is_command_available(&candidate, probe_arg) {
            return Ok(candidate);
        }
    }

    Err(anyhow!("Unable to find a usable command on PATH."))
}

fn expand_command_candidates(candidates: Vec<CommandSpec>) -> Vec<CommandSpec> {
    let mut expanded = Vec::new();

    for candidate in candidates {
        expanded.push(candidate.clone());

        #[cfg(target_os = "windows")]
        {
            if Path::new(&candidate.program).extension().is_none() {
                for extension in ["cmd", "exe", "bat"] {
                    let mut alternate = candidate.clone();
                    alternate.program = format!("{}.{}", candidate.program, extension);
                    expanded.push(alternate);
                }
            }
        }
    }

    expanded
}

fn is_command_available(command: &CommandSpec, probe_arg: &str) -> bool {
    let mut process = StdCommand::new(&command.program);
    process.args(&command.args).arg(probe_arg);
    process
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

fn allocate_port() -> Result<u16> {
    let listener =
        TcpListener::bind("127.0.0.1:0").context("Unable to reserve a loopback port.")?;
    let port = listener.local_addr()?.port();
    drop(listener);
    Ok(port)
}

fn build_codex_child(
    config: &ResolvedConfig,
    profile_file: &Path,
    profile: &ProfileDefinition,
    database: &str,
    listen_url: &str,
) -> Result<Child> {
    let launcher_path = profiled_launcher_path()?;
    let mcp_program = config.python_command.program.clone();
    let mcp_args = config.python_command.with_tail(&[
        launcher_path.display().to_string(),
        "--profile-file".to_string(),
        profile_file.display().to_string(),
        "--profile".to_string(),
        profile.id.clone(),
        "--database".to_string(),
        database.to_string(),
    ]);

    let mut command = Command::new(&config.codex_command.program);
    command
        .current_dir(&config.workspace_root)
        .args(&config.codex_command.args)
        .arg("-C")
        .arg(&config.workspace_root)
        .arg("-c")
        .arg(format!(
            "mcp_servers.{MCP_SERVER_NAME}.command={}",
            serde_json::to_string(&mcp_program)?
        ))
        .arg("-c")
        .arg(format!(
            "mcp_servers.{MCP_SERVER_NAME}.args={}",
            serde_json::to_string(&mcp_args)?
        ));

    for tool_name in AUTO_APPROVED_SQL_TSHOOTER_TOOLS {
        command.arg("-c").arg(format!(
            "mcp_servers.{MCP_SERVER_NAME}.tools.{tool_name}.approval_mode=\"approve\""
        ));
    }

    command
        .arg("app-server")
        .arg("--listen")
        .arg(listen_url)
        .stdout(Stdio::null())
        .stdin(Stdio::null())
        .stderr(Stdio::piped());

    command.spawn().context("Unable to start codex app-server.")
}

fn profiled_launcher_path() -> Result<PathBuf> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let desktop_root = manifest_dir
        .parent()
        .ok_or_else(|| anyhow!("Unable to resolve the desktop root directory."))?;
    Ok(desktop_root.join("scripts").join("run_profiled_server.py"))
}

fn resolve_mcp_log_path(workspace_root: &Path, configured_path: Option<&str>) -> PathBuf {
    configured_path
        .map(PathBuf::from)
        .unwrap_or_else(|| workspace_root.join("logs").join("sql-tshooter.log"))
}

fn read_mcp_log_tail(path: &Path) -> Option<String> {
    let content = std::fs::read_to_string(path).ok()?;
    let mut lines = content.lines().rev().take(20).collect::<Vec<_>>();
    lines.reverse();
    if lines.is_empty() {
        return None;
    }
    Some(format!(
        "Latest SQL TShooter log lines from {}:\n{}",
        path.display(),
        lines.join("\n")
    ))
}

async fn connect_with_retry(listen_url: &str) -> Result<WsStream> {
    let mut last_error: Option<anyhow::Error> = None;
    for _ in 0..40 {
        match connect_async(listen_url).await {
            Ok((socket, _)) => return Ok(socket),
            Err(error) => {
                last_error = Some(anyhow!(error));
                sleep(Duration::from_millis(250)).await;
            }
        }
    }
    Err(last_error.unwrap_or_else(|| anyhow!("Unable to connect to codex app-server.")))
}

async fn initialize_client(rpc: &Arc<JsonRpcClient>) -> Result<()> {
    rpc.request(
        "initialize",
        json!({
            "clientInfo": {
                "name": "sql-tshooter-desktop",
                "title": "SQL TShooter Desktop",
                "version": "0.1.0",
            },
            "capabilities": {
                "experimentalApi": true,
                "optOutNotificationMethods": [],
            },
        }),
    )
    .await?;

    rpc.notify("initialized", json!({})).await?;
    Ok(())
}

async fn apply_auth_status(session: &Arc<TabSession>, rpc: &Arc<JsonRpcClient>) {
    if let Ok(response) = rpc
        .request(
            "getAuthStatus",
            json!({
                "includeToken": false,
                "refreshToken": false,
            }),
        )
        .await
    {
        let auth_method = response
            .get("authMethod")
            .and_then(Value::as_str)
            .map(ToString::to_string);
        session.snapshot.write().await.auth_method = auth_method;
    }
}

async fn apply_mcp_status(session: &Arc<TabSession>, rpc: &Arc<JsonRpcClient>) {
    if let Ok(response) = rpc.request("mcpServerStatus/list", json!({})).await {
        let status = response
            .get("data")
            .and_then(Value::as_array)
            .and_then(|servers| {
                servers.iter().find(|server| {
                    server
                        .get("name")
                        .and_then(Value::as_str)
                        .map(|name| name == MCP_SERVER_NAME)
                        .unwrap_or(false)
                })
            })
            .and_then(|server| server.get("status"))
            .and_then(Value::as_str)
            .map(ToString::to_string);

        if let Some(status) = status {
            session.snapshot.write().await.mcp_status = Some(status);
        }
    }
}

async fn restore_or_start_thread(
    state: &State<'_, DesktopState>,
    session: &Arc<TabSession>,
    profile: &ProfileDefinition,
    database: &str,
    existing_thread_id: Option<String>,
) -> Result<String> {
    let response = if let Some(thread_id) = existing_thread_id.clone() {
        session
            .rpc
            .request(
                "thread/resume",
                json!({
                    "threadId": thread_id,
                    "cwd": state.config.workspace_root.display().to_string(),
                }),
            )
            .await?
    } else {
        session
            .rpc
            .request(
                "thread/start",
                json!({
                    "cwd": state.config.workspace_root.display().to_string(),
                    "approvalPolicy": "on-request",
                    "sandbox": "workspace-write",
                    "baseInstructions": format!(
                        "You are attached to SQL target '{} / {}'. Use the configured sql-tshooter MCP server for diagnostics against that target.",
                        profile.label.clone().unwrap_or_else(|| profile.id.clone()),
                        database
                    ),
                }),
            )
            .await?
    };

    let thread = response
        .get("thread")
        .cloned()
        .ok_or_else(|| anyhow!("Codex did not return a thread object."))?;

    let thread_id = thread
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("Codex thread did not include an id."))?
        .to_string();

    let turns = if existing_thread_id.is_some() {
        thread
            .get("turns")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default()
    } else {
        Vec::new()
    };

    {
        let mut snapshot = session.snapshot.write().await;
        snapshot.thread_id = Some(thread_id.clone());
        snapshot.codex_status = "ready".to_string();
        snapshot.entries = transcript_entries_from_turns(&turns);
    }
    emit_snapshot(&state.app_handle, session).await;

    Ok(thread_id)
}

async fn process_socket_messages(
    app_handle: AppHandle,
    session: Arc<TabSession>,
    rpc: Arc<JsonRpcClient>,
    mut reader: futures_util::stream::SplitStream<WsStream>,
) {
    while let Some(frame) = reader.next().await {
        match frame {
            Ok(Message::Text(payload)) => {
                if let Err(error) =
                    handle_json_rpc_message(&app_handle, &session, &rpc, &payload).await
                {
                    append_event_entry(
                        &session,
                        "error".to_string(),
                        Some("Protocol Error".to_string()),
                        Some(error.to_string()),
                        Some("failed".to_string()),
                        None,
                    )
                    .await;
                    emit_snapshot(&app_handle, &session).await;
                }
            }
            Ok(Message::Close(_)) => break,
            Ok(_) => {}
            Err(error) => {
                append_event_entry(
                    &session,
                    "error".to_string(),
                    Some("Socket Error".to_string()),
                    Some(error.to_string()),
                    Some("failed".to_string()),
                    None,
                )
                .await;
                break;
            }
        }
    }

    {
        let mut snapshot = session.snapshot.write().await;
        snapshot.codex_status = "exited".to_string();
    }
    emit_snapshot(&app_handle, &session).await;
}

async fn handle_json_rpc_message(
    app_handle: &AppHandle,
    session: &Arc<TabSession>,
    rpc: &Arc<JsonRpcClient>,
    payload: &str,
) -> Result<()> {
    let message: Value = serde_json::from_str(payload)?;

    if message.get("method").is_some() && message.get("id").is_some() {
        store_server_request(session, &message).await?;
        emit_snapshot(app_handle, session).await;
        return Ok(());
    }

    if message.get("method").is_some() {
        handle_server_notification(session, &message).await?;
        emit_snapshot(app_handle, session).await;
        return Ok(());
    }

    if let Some(id) = message.get("id") {
        let request_key = request_key(id);
        if let Some(sender) = rpc.pending.lock().await.remove(&request_key) {
            if let Some(result) = message.get("result") {
                let _ = sender.send(Ok(result.clone()));
            } else if let Some(error) = message.get("error") {
                let error_message = error
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or("Unknown RPC error.")
                    .to_string();
                let _ = sender.send(Err(DesktopError::Message(error_message)));
            }
        }
    }

    Ok(())
}

async fn store_server_request(session: &Arc<TabSession>, message: &Value) -> Result<()> {
    let method = message
        .get("method")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("Server request is missing a method."))?
        .to_string();
    let id = message
        .get("id")
        .cloned()
        .ok_or_else(|| anyhow!("Server request is missing an id."))?;
    let params = message.get("params").cloned().unwrap_or_else(|| json!({}));

    let request_key = request_key(&id);
    session
        .pending_requests
        .lock()
        .await
        .insert(request_key, PendingServerRequest { id, method, params });
    session.snapshot.write().await.pending_approvals = collect_pending_approvals(session).await;
    Ok(())
}

async fn collect_pending_approvals(session: &Arc<TabSession>) -> Vec<PendingApproval> {
    let pending = session.pending_requests.lock().await;
    pending
        .iter()
        .map(|(request_id, request)| PendingApproval {
            request_id: request_id.clone(),
            method: request.method.clone(),
            title: approval_title(&request.method),
            details: approval_details(&request.method, &request.params),
            request: Some(request.params.clone()),
        })
        .collect()
}

fn approval_title(method: &str) -> String {
    match method {
        "item/commandExecution/requestApproval" => "Command Approval".to_string(),
        "item/fileChange/requestApproval" => "File Change Approval".to_string(),
        "item/permissions/requestApproval" => "Permission Approval".to_string(),
        "item/tool/requestUserInput" => "Tool Input Requested".to_string(),
        other if other.contains("elicit") || other.contains("elicitation") => {
            "Input Requested".to_string()
        }
        _ => "Codex Request".to_string(),
    }
}

fn approval_details(method: &str, params: &Value) -> Option<String> {
    match method {
        "item/commandExecution/requestApproval" => params
            .get("command")
            .and_then(Value::as_str)
            .map(ToString::to_string),
        "item/fileChange/requestApproval" => Some(
            params
                .get("changes")
                .map(|value| value.to_string())
                .unwrap_or_else(|| "Pending file changes.".to_string()),
        ),
        "item/permissions/requestApproval" => params
            .get("reason")
            .and_then(Value::as_str)
            .map(ToString::to_string)
            .or_else(|| Some("Codex requested extra runtime permissions.".to_string())),
        "item/tool/requestUserInput" => params
            .get("questions")
            .map(|value| value.to_string())
            .or_else(|| Some("A tool requested structured user input.".to_string())),
        _ if params.get("requestedSchema").is_some() => params
            .get("message")
            .and_then(Value::as_str)
            .map(ToString::to_string)
            .or_else(|| Some("An MCP server requested structured input.".to_string())),
        _ => params
            .get("message")
            .and_then(Value::as_str)
            .map(ToString::to_string),
    }
}

async fn handle_server_notification(session: &Arc<TabSession>, message: &Value) -> Result<()> {
    let method = message
        .get("method")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow!("Notification did not include a method."))?;
    let params = message.get("params").cloned().unwrap_or_else(|| json!({}));

    match method {
        "thread/started" => {
            if let Some(thread_id) = params
                .get("thread")
                .and_then(|thread| thread.get("id"))
                .and_then(Value::as_str)
            {
                session.snapshot.write().await.thread_id = Some(thread_id.to_string());
            }
        }
        "thread/status/changed" => {
            if let Some(status) = params.get("status").and_then(Value::as_str) {
                session.snapshot.write().await.codex_status = status.to_string();
            }
        }
        "turn/started" => {
            let mut snapshot = session.snapshot.write().await;
            snapshot.codex_status = "running".to_string();
            snapshot.active_turn_id = params
                .get("turn")
                .and_then(|turn| turn.get("id"))
                .and_then(Value::as_str)
                .map(ToString::to_string);
            if let Some(turn) = params.get("turn") {
                merge_turn_items(&mut snapshot.entries, turn);
            }
        }
        "turn/completed" => {
            let mut snapshot = session.snapshot.write().await;
            snapshot.codex_status = "ready".to_string();
            snapshot.active_turn_id = None;
            if let Some(turn) = params.get("turn") {
                merge_turn_items(&mut snapshot.entries, turn);
                if let Some(error) = turn.get("error") {
                    snapshot.last_error = Some(error.to_string());
                }
            }
        }
        "item/started" | "item/completed" => {
            if let Some(item) = params.get("item") {
                upsert_entry(
                    &mut session.snapshot.write().await.entries,
                    transcript_entry_from_item(item),
                );
            }
        }
        "item/agentMessage/delta" => {
            append_delta(
                &mut session.snapshot.write().await.entries,
                params
                    .get("itemId")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
                "agentMessage",
                params
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            );
        }
        "item/plan/delta" => {
            append_delta(
                &mut session.snapshot.write().await.entries,
                params
                    .get("itemId")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
                "plan",
                params
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            );
        }
        "item/reasoning/textDelta" | "item/reasoning/summaryTextDelta" => {
            append_delta(
                &mut session.snapshot.write().await.entries,
                params
                    .get("itemId")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
                "reasoning",
                params
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            );
        }
        "item/commandExecution/outputDelta" => {
            append_delta(
                &mut session.snapshot.write().await.entries,
                params
                    .get("itemId")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
                "commandExecution",
                params
                    .get("delta")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            );
        }
        "item/mcpToolCall/progress" => {
            append_delta(
                &mut session.snapshot.write().await.entries,
                params
                    .get("itemId")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
                "mcpToolCall",
                params
                    .get("message")
                    .and_then(Value::as_str)
                    .unwrap_or_default(),
            );
        }
        "mcpServer/startupStatus/updated" => {
            if params.get("name").and_then(Value::as_str) == Some(MCP_SERVER_NAME) {
                let mut snapshot = session.snapshot.write().await;
                let previous_status = snapshot.mcp_status.clone();
                let next_status = params
                    .get("status")
                    .and_then(Value::as_str)
                    .map(ToString::to_string);
                snapshot.mcp_status = next_status.clone();
                if let Some(error) = params.get("error").and_then(Value::as_str) {
                    snapshot.last_error = Some(error.to_string());
                }
                let error_text = params
                    .get("error")
                    .and_then(Value::as_str)
                    .map(ToString::to_string);
                let status_changed = previous_status != next_status;
                let status_label = next_status
                    .clone()
                    .unwrap_or_else(|| "unknown".to_string());
                drop(snapshot);

                if status_changed || error_text.is_some() {
                    let mut message = format!(
                        "MCP server '{MCP_SERVER_NAME}' status: {}",
                        next_status.as_deref().unwrap_or("unknown")
                    );
                    if let Some(error) = error_text {
                        message.push_str(&format!(" ({error})"));
                    }
                    append_event_entry(
                        session,
                        "mcpStatus".to_string(),
                        Some("MCP Startup".to_string()),
                        Some(message),
                        Some(status_label),
                        Some(params),
                    )
                    .await;
                }

                if next_status.as_deref() == Some("failed") {
                    if let Some(log_tail) = read_mcp_log_tail(&session.mcp_log_path) {
                        append_event_entry(
                            session,
                            "mcpLog".to_string(),
                            Some("MCP Log".to_string()),
                            Some(log_tail),
                            Some("failed".to_string()),
                            Some(json!({
                                "path": session.mcp_log_path.display().to_string(),
                            })),
                        )
                        .await;
                    }
                }
            }
        }
        "warning" | "guardianWarning" | "error" => {
            append_event_entry(
                session,
                method.to_string(),
                Some(method.to_string()),
                params
                    .get("message")
                    .and_then(Value::as_str)
                    .map(ToString::to_string)
                    .or_else(|| Some(params.to_string())),
                Some("warning".to_string()),
                Some(params),
            )
            .await;
        }
        _ => {}
    }

    Ok(())
}

async fn read_process_stderr(
    app_handle: AppHandle,
    session: Arc<TabSession>,
    stderr: tokio::process::ChildStderr,
) {
    let mut reader = BufReader::new(stderr).lines();
    while let Ok(Some(line)) = reader.next_line().await {
        append_event_entry(
            &session,
            "processOutput".to_string(),
            Some("Codex Process".to_string()),
            Some(line),
            Some("info".to_string()),
            None,
        )
        .await;
        emit_snapshot(&app_handle, &session).await;
    }
}

async fn append_event_entry(
    session: &Arc<TabSession>,
    kind: String,
    title: Option<String>,
    text: Option<String>,
    status: Option<String>,
    metadata: Option<Value>,
) {
    let entry = TranscriptEntry {
        id: format!("event-{}", Uuid::new_v4()),
        kind,
        title,
        text,
        status,
        metadata,
    };
    session.snapshot.write().await.entries.push(entry);
}

async fn emit_snapshot(app_handle: &AppHandle, session: &Arc<TabSession>) {
    let snapshot = session.snapshot.read().await.clone();
    let _ = app_handle.emit(SNAPSHOT_EVENT, snapshot);
}

async fn get_session(
    state: &State<'_, DesktopState>,
    tab_id: &str,
) -> std::result::Result<Arc<TabSession>, String> {
    let sessions = state.sessions.lock().await;
    sessions
        .get(tab_id)
        .cloned()
        .ok_or_else(|| format!("Unknown tab '{tab_id}'."))
}

fn transcript_entries_from_turns(turns: &[Value]) -> Vec<TranscriptEntry> {
    let mut entries = Vec::new();
    for turn in turns {
        merge_turn_items(&mut entries, turn);
    }
    entries
}

fn merge_turn_items(entries: &mut Vec<TranscriptEntry>, turn: &Value) {
    if let Some(items) = turn.get("items").and_then(Value::as_array) {
        for item in items {
            upsert_entry(entries, transcript_entry_from_item(item));
        }
    }
}

fn transcript_entry_from_item(item: &Value) -> TranscriptEntry {
    let kind = item
        .get("type")
        .and_then(Value::as_str)
        .unwrap_or("unknown")
        .to_string();
    let id = item
        .get("id")
        .and_then(Value::as_str)
        .map(ToString::to_string)
        .unwrap_or_else(|| format!("unknown-{}", Uuid::new_v4()));

    let (title, text, status) = match kind.as_str() {
        "userMessage" => (
            Some("User".to_string()),
            Some(extract_user_message(item)),
            None,
        ),
        "agentMessage" => (
            Some("Codex".to_string()),
            item.get("text")
                .and_then(Value::as_str)
                .map(ToString::to_string),
            item.get("phase")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        ),
        "plan" => (
            Some("Plan".to_string()),
            item.get("text")
                .and_then(Value::as_str)
                .map(ToString::to_string),
            None,
        ),
        "reasoning" => (
            Some("Reasoning".to_string()),
            Some(extract_reasoning(item)),
            None,
        ),
        "commandExecution" => (
            item.get("command")
                .and_then(Value::as_str)
                .map(ToString::to_string),
            item.get("aggregatedOutput")
                .and_then(Value::as_str)
                .map(ToString::to_string),
            item.get("status")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        ),
        "mcpToolCall" => (
            Some(format!(
                "{}.{}",
                item.get("server").and_then(Value::as_str).unwrap_or("mcp"),
                item.get("tool").and_then(Value::as_str).unwrap_or("tool"),
            )),
            item.get("result").map(|value| value.to_string()),
            item.get("status")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        ),
        "fileChange" => (
            Some("File Change".to_string()),
            item.get("changes").map(|value| value.to_string()),
            item.get("status")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        ),
        other => (
            Some(other.to_string()),
            Some(item.to_string()),
            item.get("status")
                .and_then(Value::as_str)
                .map(ToString::to_string),
        ),
    };

    TranscriptEntry {
        id,
        kind,
        title,
        text,
        status,
        metadata: Some(item.clone()),
    }
}

fn extract_user_message(item: &Value) -> String {
    item.get("content")
        .and_then(Value::as_array)
        .map(|content| {
            content
                .iter()
                .filter_map(|entry| {
                    if entry.get("type").and_then(Value::as_str) == Some("text") {
                        entry.get("text").and_then(Value::as_str)
                    } else {
                        None
                    }
                })
                .collect::<Vec<_>>()
                .join("\n")
        })
        .filter(|text| !text.trim().is_empty())
        .unwrap_or_else(|| "(user message)".to_string())
}

fn extract_reasoning(item: &Value) -> String {
    let summary = item
        .get("summary")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect::<Vec<_>>();
    let content = item
        .get("content")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect::<Vec<_>>();

    [summary.join("\n"), content.join("\n")]
        .into_iter()
        .filter(|part| !part.trim().is_empty())
        .collect::<Vec<_>>()
        .join("\n\n")
}

fn upsert_entry(entries: &mut Vec<TranscriptEntry>, entry: TranscriptEntry) {
    if let Some(existing) = entries.iter_mut().find(|current| current.id == entry.id) {
        *existing = entry;
    } else {
        entries.push(entry);
    }
}

fn append_delta(entries: &mut Vec<TranscriptEntry>, id: &str, kind: &str, delta: &str) {
    if id.is_empty() || delta.is_empty() {
        return;
    }

    if let Some(existing) = entries.iter_mut().find(|entry| entry.id == id) {
        let current = existing.text.clone().unwrap_or_default();
        existing.text = Some(format!("{current}{delta}"));
        if existing.title.is_none() {
            existing.title = Some(kind.to_string());
        }
        return;
    }

    entries.push(TranscriptEntry {
        id: id.to_string(),
        kind: kind.to_string(),
        title: Some(kind.to_string()),
        text: Some(delta.to_string()),
        status: Some("streaming".to_string()),
        metadata: None,
    });
}

fn request_key(id: &Value) -> String {
    match id {
        Value::String(value) => value.clone(),
        _ => id.to_string(),
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let state = DesktopState::initialize(app.handle().clone())?;
            app.manage(state);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            bootstrap_app,
            set_profile_file,
            pick_profile_file,
        open_target_tab,
        get_tab_snapshot,
        send_prompt,
        interrupt_turn,
        clear_target_conversation,
        respond_to_approval,
        close_target_tab,
    ])
        .run(tauri::generate_context!())
        .expect("error while running sql-tshooter desktop");
}
