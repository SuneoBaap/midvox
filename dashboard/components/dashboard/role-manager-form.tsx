"use client";

import React, { useMemo, useState } from "react";
import { Check, ChevronDown, Crown, Layers3, Loader2, Palette, Save, Shield, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { DiscordRole, RoleMutation } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Preset = "normal" | "high" | "all" | "custom";

const PERMISSION_GROUPS = [
  { name: "General", permissions: [
    ["view_channel", "View Channels"], ["create_instant_invite", "Create Invites"],
    ["change_nickname", "Change Nickname"], ["manage_nicknames", "Manage Nicknames"],
    ["view_audit_log", "View Audit Log"], ["manage_channels", "Manage Channels"],
    ["manage_roles", "Manage Roles"], ["manage_webhooks", "Manage Webhooks"],
    ["manage_guild", "Manage Server"],
  ]},
  { name: "Members", permissions: [
    ["kick_members", "Kick Members"], ["ban_members", "Ban Members"],
    ["moderate_members", "Timeout Members"],
  ]},
  { name: "Text", permissions: [
    ["send_messages", "Send Messages"], ["send_messages_in_threads", "Send in Threads"],
    ["create_public_threads", "Create Public Threads"], ["create_private_threads", "Create Private Threads"],
    ["manage_threads", "Manage Threads"], ["manage_messages", "Manage Messages"],
    ["read_message_history", "Read Message History"], ["add_reactions", "Add Reactions"],
    ["embed_links", "Embed Links"], ["attach_files", "Attach Files"],
    ["mention_everyone", "Mention Everyone"], ["use_external_emojis", "External Emojis"],
    ["use_external_stickers", "External Stickers"], ["use_application_commands", "Application Commands"],
  ]},
  { name: "Voice", permissions: [
    ["connect", "Connect"], ["speak", "Speak"], ["stream", "Video / Stream"],
    ["use_voice_activation", "Voice Activity"], ["priority_speaker", "Priority Speaker"],
    ["mute_members", "Mute Members"], ["deafen_members", "Deafen Members"],
    ["move_members", "Move Members"],
  ]},
  { name: "Advanced", permissions: [["administrator", "Administrator"]] },
] as const;

const ALL_VISIBLE = PERMISSION_GROUPS.flatMap(group => group.permissions.map(([id]) => id));
const NORMAL = [
  "view_channel", "send_messages", "send_messages_in_threads", "create_public_threads",
  "read_message_history", "add_reactions", "embed_links", "attach_files", "use_external_emojis",
  "use_external_stickers", "use_application_commands", "connect", "speak", "stream",
  "use_voice_activation", "change_nickname",
];
const HIGH = Array.from(new Set([
  ...NORMAL, "create_private_threads", "manage_threads", "manage_nicknames", "manage_messages",
  "manage_channels", "manage_roles", "manage_webhooks", "view_audit_log", "kick_members",
  "ban_members", "moderate_members", "mute_members", "deafen_members", "move_members",
]));

const PRESETS = [
  { id: "normal" as Preset, name: "Normal", detail: "Everyday community access", icon: Shield },
  { id: "high" as Preset, name: "High", detail: "Trusted moderation access", icon: Crown },
  { id: "all" as Preset, name: "All Permissions", detail: "Administrator-level access", icon: Sparkles },
];

const hexColor = (value: number) => `#${value.toString(16).padStart(6, "0")}`;

export function RoleManagerForm({ guildId, initialRoles }: { guildId: string; initialRoles: DiscordRole[] }) {
  const [roles, setRoles] = useState(initialRoles);
  const [editingId, setEditingId] = useState("new");
  const [name, setName] = useState("");
  const [color, setColor] = useState("#b7d56a");
  const [preset, setPreset] = useState<Preset>("normal");
  const [permissions, setPermissions] = useState<string[]>(NORMAL);
  const [customized, setCustomized] = useState(false);
  const [hoist, setHoist] = useState(false);
  const [mentionable, setMentionable] = useState(false);
  const [belowRoleId, setBelowRoleId] = useState("");
  const [saving, setSaving] = useState(false);

  const editableRoles = useMemo(
    () => roles.filter(role => role.name !== "@everyone" && !role.managed),
    [roles]
  );
  const positionRoles = roles.filter(role => role.name !== "@everyone" && role.id !== editingId);

  const choosePreset = (next: Preset) => {
    setPreset(next);
    setCustomized(false);
    setPermissions(next === "normal" ? NORMAL : next === "high" ? HIGH : ALL_VISIBLE);
  };

  const togglePermission = (permission: string) => {
    setCustomized(true);
    setPreset("custom");
    setPermissions(current => current.includes(permission)
      ? current.filter(item => item !== permission)
      : [...current, permission]);
  };

  const selectRole = (value: string) => {
    setEditingId(value);
    if (value === "new") {
      setName("");
      setColor("#b7d56a");
      setHoist(false);
      setMentionable(false);
      setBelowRoleId("");
      choosePreset("normal");
      return;
    }
    const role = roles.find(item => item.id === value);
    if (!role) return;
    setName(role.name);
    setColor(hexColor(role.color));
    setPermissions(role.permissions || []);
    setPreset("custom");
    setCustomized(true);
    setHoist(role.hoist);
    setMentionable(role.mentionable);
    setBelowRoleId("");
  };

  const saveRole = async () => {
    if (!name.trim()) return toast.error("Enter a role name.");
    if (belowRoleId && !/^\d{17,20}$/.test(belowRoleId)) {
      return toast.error("Enter a valid Discord role ID for the position.");
    }
    const payload: RoleMutation = {
      name: name.trim(),
      color: parseInt(color.replace("#", ""), 16),
      preset,
      permissions: customized || preset === "custom" ? permissions : undefined,
      hoist,
      mentionable,
      below_role_id: belowRoleId || null,
    };
    setSaving(true);
    try {
      const saved = editingId === "new"
        ? await api.createRole(guildId, payload)
        : await api.updateRole(guildId, editingId, payload);
      const refreshed = await api.getRoles(guildId);
      setRoles(refreshed);
      setEditingId(saved.id);
      setPermissions(saved.permissions || []);
      setPreset("custom");
      setCustomized(true);
      toast.success(editingId === "new" ? `${saved.name} was created in Discord.` : `${saved.name} was updated.`);
    } catch (error: any) {
      toast.error(error?.message || "Discord could not save this role.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
      <section className="space-y-6 rounded-2xl border border-[var(--panel-line)] bg-[var(--panel-paper)] p-5 md:p-7">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.22em] text-primary">Discord role studio</p>
            <h3 className="mt-2 text-xl font-bold text-[var(--panel-ink)]">Create or customize a role</h3>
            <p className="mt-1 text-sm text-[var(--panel-muted)]">Presets are a starting point. Every permission remains editable.</p>
          </div>
          <div className="w-full md:w-72">
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-wider text-[var(--panel-muted)]">Mode</label>
            <Select value={editingId} onValueChange={selectRole}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="new">Create a new role</SelectItem>
                {editableRoles.map(role => <SelectItem key={role.id} value={role.id}>Edit • {role.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-[1fr_160px]">
          <div>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-wider text-[var(--panel-muted)]">Role name</label>
            <Input value={name} onChange={event => setName(event.target.value)} maxLength={100} placeholder="Community Manager" />
          </div>
          <div>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-wider text-[var(--panel-muted)]">Color</label>
            <div className="flex h-10 items-center gap-2 rounded-md border border-[var(--panel-line)] px-3">
              <Palette className="h-4 w-4 text-[var(--panel-muted)]" />
              <input className="h-6 w-full cursor-pointer bg-transparent" type="color" value={color} onChange={event => setColor(event.target.value)} />
            </div>
          </div>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {PRESETS.map(item => {
            const active = preset === item.id && !customized;
            return (
              <button key={item.id} type="button" onClick={() => choosePreset(item.id)}
                className={cn("rounded-xl border p-4 text-left transition", active ? "border-primary bg-primary/10" : "border-[var(--panel-line)] hover:border-primary/50")}>
                <div className="flex items-center justify-between">
                  <item.icon className={cn("h-5 w-5", active ? "text-primary" : "text-[var(--panel-muted)]")} />
                  {active && <Check className="h-4 w-4 text-primary" />}
                </div>
                <p className="mt-3 text-sm font-bold text-[var(--panel-ink)]">{item.name}</p>
                <p className="mt-1 text-xs text-[var(--panel-muted)]">{item.detail}</p>
              </button>
            );
          })}
        </div>

        {preset === "all" && !customized && (
          <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 p-4 text-xs text-amber-200">
            All Permissions includes Administrator and bypasses channel permission restrictions. Use it only for fully trusted staff.
          </div>
        )}

        <div className="space-y-5">
          {PERMISSION_GROUPS.map(group => (
            <div key={group.name}>
              <h4 className="mb-3 text-xs font-bold uppercase tracking-wider text-[var(--panel-muted)]">{group.name}</h4>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {group.permissions.map(([id, label]) => {
                  const checked = permissions.includes(id);
                  return (
                    <button key={id} type="button" onClick={() => togglePermission(id)}
                      className={cn("flex items-center justify-between rounded-lg border px-3 py-2.5 text-left text-xs transition", checked ? "border-primary/50 bg-primary/10 text-[var(--panel-ink)]" : "border-[var(--panel-line)] text-[var(--panel-muted)] hover:border-primary/30")}>
                      {label}<span className={cn("h-4 w-4 rounded border", checked && "border-primary bg-primary")} />
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        <div className="grid gap-4 border-t border-[var(--panel-line)] pt-6 md:grid-cols-2">
          <div>
            <label className="mb-2 block text-[10px] font-semibold uppercase tracking-wider text-[var(--panel-muted)]">Place directly below role ID</label>
            <Input value={belowRoleId} onChange={event => setBelowRoleId(event.target.value.trim())} placeholder="Paste a role ID" inputMode="numeric" />
            <Select value={belowRoleId || "none"} onValueChange={value => setBelowRoleId(value === "none" ? "" : value)}>
              <SelectTrigger className="mt-2"><SelectValue placeholder="Or choose a role" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="none">Keep Discord&apos;s current/default position</SelectItem>
                {positionRoles.map(role => <SelectItem key={role.id} value={role.id}>Below {role.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-xl border border-[var(--panel-line)] p-4">
              <div><p className="text-sm font-semibold">Display separately</p><p className="text-xs text-[var(--panel-muted)]">Show members in their own section.</p></div>
              <Switch checked={hoist} onCheckedChange={setHoist} />
            </div>
            <div className="flex items-center justify-between rounded-xl border border-[var(--panel-line)] p-4">
              <div><p className="text-sm font-semibold">Mentionable</p><p className="text-xs text-[var(--panel-muted)]">Allow members to mention this role.</p></div>
              <Switch checked={mentionable} onCheckedChange={setMentionable} />
            </div>
          </div>
        </div>

        <Button onClick={saveRole} disabled={saving} className="h-12 w-full gap-2 font-bold">
          {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {editingId === "new" ? "Create role in Discord" : "Save role changes"}
        </Button>
      </section>

      <aside className="space-y-4">
        <div className="rounded-2xl border border-primary/20 bg-primary/5 p-5">
          <Layers3 className="h-6 w-6 text-primary" />
          <h3 className="mt-4 font-bold text-[var(--panel-ink)]">Hierarchy-aware</h3>
          <p className="mt-2 text-xs leading-5 text-[var(--panel-muted)]">Paste the ID of an existing role and MidVox places the new role directly beneath it. The bot must be above that position.</p>
        </div>
        <div className="rounded-2xl border border-[var(--panel-line)] bg-[var(--panel-paper)] p-5">
          <p className="text-xs font-bold uppercase tracking-wider text-[var(--panel-muted)]">Current selection</p>
          <div className="mt-4 flex items-center gap-3">
            <span className="h-9 w-9 rounded-full" style={{ backgroundColor: color }} />
            <div><p className="font-bold text-[var(--panel-ink)]">{name || "Unnamed role"}</p><p className="text-xs text-[var(--panel-muted)]">{permissions.length} visible permissions selected</p></div>
          </div>
        </div>
      </aside>
    </div>
  );
}
