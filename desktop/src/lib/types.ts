export type ProfileSummary = {
  id: string;
  label: string;
  host: string;
  defaultDatabase: string | null;
  databases: string[];
  authMode: string;
  credentialStatus: "notRequired" | "ready" | "missing" | "unsupported";
};

export type RestoredTarget = {
  tabId: string;
  profileId: string;
  database: string;
};

export type BootstrapPayload = {
  profileFile: string;
  workspaceRoot: string;
  profiles: ProfileSummary[];
  restoredTargets: RestoredTarget[];
  profileLoadError: string | null;
};

export type TranscriptEntry = {
  id: string;
  kind: string;
  title: string | null;
  text: string | null;
  status: string | null;
  metadata: Record<string, unknown> | null;
};

export type PendingApproval = {
  requestId: string;
  method: string;
  title: string;
  details: string | null;
  request: Record<string, unknown> | null;
};

export type TabSnapshot = {
  id: string;
  targetKey: string;
  profileId: string;
  profileLabel: string;
  database: string;
  threadId: string | null;
  codexStatus: string;
  authMethod: string | null;
  mcpStatus: string | null;
  activeTurnId: string | null;
  lastError: string | null;
  entries: TranscriptEntry[];
  pendingApprovals: PendingApproval[];
};

export type ApprovalAction =
  | "accept"
  | "acceptForSession"
  | "decline"
  | "cancel"
  | "acceptPermissionsForTurn"
  | "acceptPermissionsForSession"
  | "submitAnswers";
