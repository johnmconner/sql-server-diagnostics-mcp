import { useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import {
  bootstrapApp,
  clearTargetConversation,
  closeTargetTab,
  interruptTurn,
  listenForTabSnapshots,
  openTargetTab,
  pickProfileFile,
  respondToApproval,
  saveProfileCredential,
  sendPrompt,
  setProfileFile,
} from "./lib/api";
import type {
  BootstrapPayload,
  PendingApproval,
  ProfileSummary,
  TabSnapshot,
  TranscriptEntry,
} from "./lib/types";

type AppState = {
  profileFile: string;
  workspaceRoot: string;
  profiles: ProfileSummary[];
  profileLoadError: string | null;
};

type DisplayEntry = {
  id: string;
  prefix: string;
  text: string;
  status: string | null;
  tone: "message" | "status" | "error";
  preformatted?: boolean;
};

const EMPTY_STATE: AppState = {
  profileFile: "",
  workspaceRoot: "",
  profiles: [],
  profileLoadError: null,
};

const ANSI_PATTERN = /\u001b\[[0-9;]*m/g;

type ApprovalDecision =
  | "accept"
  | "acceptForSession"
  | "decline"
  | "cancel"
  | "acceptPermissionsForTurn"
  | "acceptPermissionsForSession";

function stripAnsi(text: string) {
  return text.replace(ANSI_PATTERN, "");
}

function entryPrefix(entry: TranscriptEntry) {
  switch (entry.kind) {
    case "userMessage":
      return ">";
    case "agentMessage":
      return "codex";
    case "mcpStatus":
      return "mcp";
    case "processOutput":
      return "codex";
    case "warning":
    case "guardianWarning":
    case "error":
      return "status";
    default:
      return entry.title?.toLowerCase() || entry.kind;
  }
}

function entryText(entry: TranscriptEntry) {
  if (entry.text?.trim()) {
    return stripAnsi(entry.text).trim();
  }
  return "";
}

function isImportantProcessLine(text: string) {
  return /(error|warn|failed|exception)/i.test(text);
}

function metadataString(
  entry: TranscriptEntry,
  key: string,
) {
  const value = entry.metadata?.[key];
  return typeof value === "string" ? value : null;
}

function toDisplayEntry(entry: TranscriptEntry): DisplayEntry | null {
  const text = entryText(entry);

  switch (entry.kind) {
    case "userMessage":
    case "agentMessage":
      if (!text) {
        return null;
      }
      return {
        id: entry.id,
        prefix: entryPrefix(entry),
        text,
        status: entry.status,
        tone: "message",
      };
    case "mcpStatus":
      if (!text) {
        return null;
      }
      return {
        id: entry.id,
        prefix: entryPrefix(entry),
        text,
        status: entry.status,
        tone: entry.status === "failed" ? "error" : "status",
      };
    case "mcpToolCall": {
      const server = metadataString(entry, "server") || "mcp";
      const tool = metadataString(entry, "tool") || entry.title || "tool";
      const summary = `${server}.${tool}`;
      return {
        id: entry.id,
        prefix: "mcp",
        text: summary,
        status: entry.status,
        tone: entry.status === "failed" ? "error" : "status",
      };
    }
    case "warning":
    case "guardianWarning":
    case "error":
      if (!text) {
        return null;
      }
      return {
        id: entry.id,
        prefix: entryPrefix(entry),
        text,
        status: entry.status,
        tone: "error",
      };
    case "processOutput":
      if (!text || !isImportantProcessLine(text)) {
        return null;
      }
      return {
        id: entry.id,
        prefix: entryPrefix(entry),
        text,
        status: entry.status,
        tone: "error",
        preformatted: true,
      };
    default:
      return null;
  }
}

function approvalActions(approval: PendingApproval) {
  if (approval.method === "item/permissions/requestApproval") {
    return [
      { label: "Allow Turn", value: "acceptPermissionsForTurn" as const },
      { label: "Allow Session", value: "acceptPermissionsForSession" as const },
      { label: "Decline", value: "decline" as const },
    ];
  }

  if (
    approval.method === "item/tool/requestUserInput" ||
    approval.method.includes("elicit") ||
    approval.method.includes("elicitation") ||
    Boolean(approval.request?.requestedSchema)
  ) {
    return [
      { label: "Approve", value: "accept" as const },
      { label: "Decline", value: "decline" as const },
    ];
  }

  return [
    { label: "Approve", value: "accept" as const },
    { label: "Approve Session", value: "acceptForSession" as const },
    { label: "Decline", value: "decline" as const },
  ];
}

export default function App() {
  const [appState, setAppState] = useState<AppState>(EMPTY_STATE);
  const [tabs, setTabs] = useState<Record<string, TabSnapshot>>({});
  const [tabOrder, setTabOrder] = useState<string[]>([]);
  const [activeTabId, setActiveTabId] = useState<string | null>(null);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [selectedDatabase, setSelectedDatabase] = useState("");
  const [profilePathDraft, setProfilePathDraft] = useState("");
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);
  const [approvalBusyId, setApprovalBusyId] = useState<string | null>(null);
  const terminalLogRef = useRef<HTMLElement | null>(null);
  const shouldAutoScrollRef = useRef(true);

  function applyPayload(payload: BootstrapPayload, restoreTargets: boolean) {
    setAppState({
      profileFile: payload.profileFile,
      workspaceRoot: payload.workspaceRoot,
      profiles: payload.profiles,
      profileLoadError: payload.profileLoadError,
    });
    setProfilePathDraft(payload.profileFile);

    const firstProfile = payload.profiles[0];
    if (firstProfile) {
      setSelectedProfileId((current) => {
        if (payload.profiles.some((profile) => profile.id === current)) {
          return current;
        }
        return firstProfile.id;
      });
      setSelectedDatabase((current) => {
        const activeProfile =
          payload.profiles.find((profile) => profile.id === selectedProfileId) || firstProfile;
        if (activeProfile.databases.includes(current)) {
          return current;
        }
        return activeProfile.defaultDatabase || activeProfile.databases[0] || "";
      });
    } else {
      setSelectedProfileId("");
      setSelectedDatabase("");
    }

    if (restoreTargets) {
      for (const target of payload.restoredTargets) {
        openTargetTab(target.profileId, target.database).catch((error) => {
          setBootError(String(error));
        });
      }
    }
  }

  useEffect(() => {
    let mounted = true;
    let unlisten: (() => void) | undefined;

    bootstrapApp()
      .then(async (payload) => {
        if (!mounted) {
          return;
        }

        unlisten = await listenForTabSnapshots((snapshot) => {
          setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
          setTabOrder((current) =>
            current.includes(snapshot.id) ? current : [...current, snapshot.id],
          );
          setActiveTabId((current) => current ?? snapshot.id);
        });

        applyPayload(payload, true);
      })
      .catch((error) => {
        if (mounted) {
          setBootError(String(error));
        }
      });

    return () => {
      mounted = false;
      if (unlisten) {
        void unlisten();
      }
    };
  }, []);

  const selectedProfile = useMemo(
    () => appState.profiles.find((profile) => profile.id === selectedProfileId) ?? null,
    [appState.profiles, selectedProfileId],
  );

  useEffect(() => {
    if (!selectedProfile) {
      return;
    }
    if (!selectedProfile.databases.includes(selectedDatabase)) {
      setSelectedDatabase(
        selectedProfile.defaultDatabase || selectedProfile.databases[0] || "",
      );
    }
  }, [selectedDatabase, selectedProfile]);

  const activeTab = activeTabId ? tabs[activeTabId] ?? null : null;
  const displayEntries = useMemo(
    () =>
      activeTab?.entries
        .map(toDisplayEntry)
        .filter((entry): entry is DisplayEntry => entry !== null) ?? [],
    [activeTab],
  );
  const needsProfileSetup =
    !bootError && (!appState.profiles.length || Boolean(appState.profileLoadError));

  useEffect(() => {
    shouldAutoScrollRef.current = true;
  }, [activeTabId]);

  useEffect(() => {
    const node = terminalLogRef.current;
    if (!node || !shouldAutoScrollRef.current) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [activeTabId, displayEntries]);

  function handleTranscriptScroll(event: UIEvent<HTMLElement>) {
    const node = event.currentTarget;
    shouldAutoScrollRef.current =
      node.scrollHeight - node.scrollTop - node.clientHeight < 24;
  }

  async function handleConnect() {
    if (!selectedProfileId || !selectedDatabase) {
      return;
    }

    setBusy(true);
    setBootError(null);
    try {
      if (selectedProfile?.authMode === "sql" && selectedProfile.credentialStatus === "missing") {
        const password = window.prompt(`Enter the SQL password for ${selectedProfile.label}.`);
        if (password === null) {
          return;
        }
        const payload = await saveProfileCredential(selectedProfile.id, password);
        applyPayload(payload, false);
      }

      const snapshot = await openTargetTab(selectedProfileId, selectedDatabase);
      setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
      setTabOrder((current) =>
        current.includes(snapshot.id) ? current : [...current, snapshot.id],
      );
      setActiveTabId(snapshot.id);
    } catch (error) {
      setBootError(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveCredential() {
    if (!selectedProfile || selectedProfile.authMode !== "sql") {
      return;
    }

    const password = window.prompt(`Enter the SQL password for ${selectedProfile.label}.`);
    if (password === null) {
      return;
    }

    setBusy(true);
    setBootError(null);
    try {
      const payload = await saveProfileCredential(selectedProfile.id, password);
      applyPayload(payload, false);
    } catch (error) {
      setBootError(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleSendPrompt() {
    if (!activeTab || !prompt.trim()) {
      return;
    }

    setBusy(true);
    try {
      const snapshot = await sendPrompt(activeTab.id, prompt.trim());
      setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
      setPrompt("");
    } finally {
      setBusy(false);
    }
  }

  async function handleInterrupt() {
    if (!activeTab) {
      return;
    }

    setBusy(true);
    try {
      const snapshot = await interruptTurn(activeTab.id);
      setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
    } finally {
      setBusy(false);
    }
  }

  async function handleClearConversation() {
    if (!activeTab) {
      return;
    }

    setBusy(true);
    setBootError(null);
    try {
      const snapshot = await clearTargetConversation(activeTab.id);
      setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
    } catch (error) {
      setBootError(String(error));
    } finally {
      setBusy(false);
    }
  }

  async function handleCloseTab(tabId: string) {
    await closeTargetTab(tabId);
    const remaining = tabOrder.filter((id) => id !== tabId);
    setTabs((current) => {
      const next = { ...current };
      delete next[tabId];
      return next;
    });
    setTabOrder(remaining);
    setActiveTabId((current) => (current === tabId ? remaining[0] ?? null : current));
  }

  async function handleApprovalAction(
    approval: PendingApproval,
    action: ApprovalDecision,
  ) {
    if (!activeTab) {
      return;
    }

    setApprovalBusyId(approval.requestId);
    setBootError(null);
    try {
      const snapshot = await respondToApproval(activeTab.id, approval.requestId, action);
      setTabs((current) => ({ ...current, [snapshot.id]: snapshot }));
    } catch (error) {
      setBootError(String(error));
    } finally {
      setApprovalBusyId((current) =>
        current === approval.requestId ? null : current,
      );
    }
  }

  async function handlePickProfileFile() {
    setBusy(true);
    try {
      const payload = await pickProfileFile();
      if (payload) {
        setBootError(null);
        applyPayload(payload, false);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleUseProfilePath() {
    if (!profilePathDraft.trim()) {
      return;
    }

    setBusy(true);
    try {
      const payload = await setProfileFile(profilePathDraft.trim());
      setBootError(null);
      applyPayload(payload, false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">SQL TShooter</div>

        <div className="control-strip">
          <select
            className="control"
            value={selectedProfileId}
            disabled={!appState.profiles.length}
            onChange={(event) => setSelectedProfileId(event.target.value)}
          >
            {appState.profiles.length ? null : (
              <option value="">No profiles loaded</option>
            )}
            {appState.profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.label}
              </option>
            ))}
          </select>

          <select
            className="control"
            value={selectedDatabase}
            disabled={!selectedProfile}
            onChange={(event) => setSelectedDatabase(event.target.value)}
          >
            {(selectedProfile?.databases || []).map((database) => (
              <option key={database} value={database}>
                {database}
              </option>
            ))}
          </select>

          <button className="control-button" disabled={busy || !selectedProfile} onClick={handleConnect}>
            {busy ? "Working..." : "Connect"}
          </button>
          {selectedProfile?.authMode === "sql" ? (
            <button className="control-button" disabled={busy} onClick={handleSaveCredential}>
              {selectedProfile.credentialStatus === "ready" ? "Update Credential" : "Save Credential"}
            </button>
          ) : null}
        </div>

        <div className="topbar-status">
          {activeTab
            ? `${activeTab.profileLabel}/${activeTab.database} - ${activeTab.codexStatus}`
            : selectedProfile?.authMode === "sql"
              ? `Credential: ${selectedProfile.credentialStatus}`
              : "No active session"}
        </div>
      </header>

      {tabOrder.length > 1 ? (
        <nav className="tab-strip">
          {tabOrder.map((tabId) => {
            const tab = tabs[tabId];
            if (!tab) {
              return null;
            }

            return (
              <button
                key={tabId}
                className={tabId === activeTabId ? "tab active" : "tab"}
                onClick={() => setActiveTabId(tabId)}
              >
                {tab.profileLabel}/{tab.database}
              </button>
            );
          })}
        </nav>
      ) : null}

      {bootError ? <div className="banner error">{bootError}</div> : null}

      {needsProfileSetup ? (
        <section className="setup-panel">
          <div className="setup-copy">
            <h1>Profiles file</h1>
            <p>{appState.profileLoadError || "Select a profiles.json file to continue."}</p>
          </div>

          <label className="setup-field">
            <span>Path</span>
            <input
              value={profilePathDraft}
              onChange={(event) => setProfilePathDraft(event.target.value)}
              placeholder="profiles.json"
            />
          </label>

          <div className="setup-actions">
            <button className="control-button" disabled={busy} onClick={handlePickProfileFile}>
              Browse
            </button>
            <button className="control-button primary" disabled={busy || !profilePathDraft.trim()} onClick={handleUseProfilePath}>
              Use Path
            </button>
          </div>
        </section>
      ) : (
        <main className="terminal-shell">
          {activeTab ? (
            <>
              <div className="session-line">
                <span>{activeTab.profileLabel}</span>
                <span>{activeTab.database}</span>
                <span>{activeTab.codexStatus}</span>
                {activeTab.mcpStatus ? <span>mcp:{activeTab.mcpStatus}</span> : null}
                <div className="session-actions">
                  <button
                    className="control-button"
                    onClick={handleClearConversation}
                    disabled={Boolean(activeTab.activeTurnId) || busy}
                  >
                    Clear
                  </button>
                  <button
                    className="control-button"
                    onClick={handleInterrupt}
                    disabled={!activeTab.activeTurnId || busy}
                  >
                    Interrupt
                  </button>
                  <button className="control-button" onClick={() => handleCloseTab(activeTab.id)}>
                    Close
                  </button>
                </div>
              </div>

              {activeTab.pendingApprovals.length > 0 ? (
                <section className="approval-strip">
                  {activeTab.pendingApprovals.map((approval) => (
                    <article className="approval-box" key={approval.requestId}>
                      <div className="approval-text">
                        <strong>{approval.title}</strong>
                        <span>{approval.details || approval.method}</span>
                      </div>
                      <div className="approval-actions">
                        {approvalActions(approval).map((action) => (
                          <button
                            key={action.value}
                            type="button"
                            className="control-button"
                            disabled={approvalBusyId === approval.requestId}
                            onClick={() => handleApprovalAction(approval, action.value)}
                          >
                            {approvalBusyId === approval.requestId ? "Working..." : action.label}
                          </button>
                        ))}
                      </div>
                    </article>
                  ))}
                </section>
              ) : null}

              <section
                className="terminal-log"
                ref={terminalLogRef}
                onScroll={handleTranscriptScroll}
              >
                {displayEntries.length ? (
                  displayEntries.map((entry) => {
                    const entryClassName =
                      entry.tone === "error"
                        ? "terminal-entry terminal-entry-error"
                        : entry.tone === "status"
                          ? "terminal-entry terminal-entry-status"
                          : "terminal-entry";

                    return (
                      <article className={entryClassName} key={entry.id}>
                        <div className="entry-prefix">
                          <span>{entry.prefix}</span>
                          {entry.status ? <em>{entry.status}</em> : null}
                        </div>
                        {entry.preformatted ? (
                          <pre>{entry.text}</pre>
                        ) : (
                          <p>{entry.text}</p>
                        )}
                      </article>
                    );
                  })
                ) : (
                  <div className="terminal-empty">
                    Session ready. Send a prompt to start Codex on this target.
                  </div>
                )}
              </section>

              <div className="composer">
                <textarea
                  placeholder="Ask Codex about the selected SQL target..."
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                />
                <button
                  className="control-button primary"
                  disabled={busy || !prompt.trim()}
                  onClick={handleSendPrompt}
                >
                  Send
                </button>
              </div>
            </>
          ) : (
            <section className="terminal-log">
              <div className="terminal-empty">
                Pick a server and database, then connect.
              </div>
            </section>
          )}
        </main>
      )}
    </div>
  );
}
