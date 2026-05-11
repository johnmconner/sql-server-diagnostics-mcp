import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type {
  ApprovalAction,
  BootstrapPayload,
  TabSnapshot,
} from "./types";

export async function bootstrapApp(): Promise<BootstrapPayload> {
  return invoke<BootstrapPayload>("bootstrap_app");
}

export async function setProfileFile(profileFile: string): Promise<BootstrapPayload> {
  return invoke<BootstrapPayload>("set_profile_file", { profileFile });
}

export async function pickProfileFile(): Promise<BootstrapPayload | null> {
  return invoke<BootstrapPayload | null>("pick_profile_file");
}

export async function openTargetTab(
  profileId: string,
  database: string,
): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("open_target_tab", { profileId, database });
}

export async function getTabSnapshot(tabId: string): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("get_tab_snapshot", { tabId });
}

export async function sendPrompt(tabId: string, text: string): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("send_prompt", { tabId, text });
}

export async function interruptTurn(tabId: string): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("interrupt_turn", { tabId });
}

export async function clearTargetConversation(tabId: string): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("clear_target_conversation", { tabId });
}

export async function closeTargetTab(tabId: string): Promise<void> {
  return invoke("close_target_tab", { tabId });
}

export async function respondToApproval(
  tabId: string,
  requestId: string,
  action: ApprovalAction,
  answers?: Record<string, string>,
): Promise<TabSnapshot> {
  return invoke<TabSnapshot>("respond_to_approval", {
    tabId,
    requestId,
    action,
    answers,
  });
}

export async function listenForTabSnapshots(
  handler: (snapshot: TabSnapshot) => void,
): Promise<UnlistenFn> {
  return listen<TabSnapshot>("desktop://tab-snapshot", (event) => {
    handler(event.payload);
  });
}
