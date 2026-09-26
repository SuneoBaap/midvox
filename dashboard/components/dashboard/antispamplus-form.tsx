"use client";

import React, { useState, useEffect } from "react";
import { Save, RefreshCcw, Trash2, Plus, Info, MessageSquare, SmilePlus, UserX, Command, Hash, Users, Flame, ShieldCheck, UserPlus } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

interface AntiSpamPlusFormProps {
  initialConfig: any;
  channels: any[];
  roles: any[];
  guildId: string;
}

export function AntiSpamPlusForm({ initialConfig, channels, roles, guildId }: AntiSpamPlusFormProps) {
  const [config, setConfig] = useState<any>(initialConfig);
  const [saving, setSaving] = useState(false);
  const [newUserId, setNewUserId] = useState("");
  const [newCommand, setNewCommand] = useState("");

  useEffect(() => {
    setConfig(initialConfig);
  }, [initialConfig]);

  const handleSave = async () => {
    setSaving(true);
    const data: any = {
      delete_messages: config.delete_messages,
      delete_delay: config.delete_delay,
      re_limit: config.re_limit,
      re_window: config.re_window,
      re_cooldown: config.re_cooldown,
      re_delay: config.re_delay,
      timeout_duration: config.timeout_duration,
      heat_enabled: config.heat_enabled,
      heat_threshold: config.heat_threshold,
      heat_decay_per_second: config.heat_decay_per_second,
      heat_timeout_minutes: config.heat_timeout_minutes,
      heat_delete_messages: config.heat_delete_messages,
      raid_trigger_users: config.raid_trigger_users,
      raid_window_seconds: config.raid_window_seconds,
      panic_minutes: config.panic_minutes,
      join_gate_enabled: config.join_gate_enabled,
      min_account_age_hours: config.min_account_age_hours,
      block_no_avatar: config.block_no_avatar,
      block_unverified_bots: config.block_unverified_bots,
    };
    const promise = api.updateAntiSpamPlus(guildId, data);
    toast.promise(promise, {
      loading: "Saving Anti-Spam+ configuration...",
      success: "Settings saved successfully!",
      error: "Failed to update config",
    });
    try {
      const result = await promise;
      setConfig(result);
    } catch (err: any) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const addTargetUser = async () => {
    if (!newUserId || !/^\d+$/.test(newUserId)) {
      toast.error("Enter a valid Discord user ID");
      return;
    }
    try {
      const result = await api.updateAntiSpamPlus(guildId, { add_target_user: newUserId });
      setConfig((prev: any) => ({ ...prev, target_users: result.target_users }));
      setNewUserId("");
      toast.success("Target user added");
    } catch { toast.error("Failed to add user"); }
  };

  const removeTargetUser = async (userId: string) => {
    try {
      const result = await api.updateAntiSpamPlus(guildId, { remove_target_user: userId });
      setConfig((prev: any) => ({ ...prev, target_users: result.target_users }));
      toast.success("Target user removed");
    } catch { toast.error("Failed to remove user"); }
  };

  const addBlockedCommand = async () => {
    if (!newCommand.trim()) {
      toast.error("Enter a command");
      return;
    }
    try {
      const result = await api.updateAntiSpamPlus(guildId, { add_blocked_command: newCommand.trim() });
      setConfig((prev: any) => ({ ...prev, blocked_commands: result.blocked_commands }));
      setNewCommand("");
      toast.success("Blocked command added");
    } catch { toast.error("Failed to add command"); }
  };

  const removeBlockedCommand = async (cmd: string) => {
    try {
      const result = await api.updateAntiSpamPlus(guildId, { remove_blocked_command: cmd });
      setConfig((prev: any) => ({ ...prev, blocked_commands: result.blocked_commands }));
      toast.success("Blocked command removed");
    } catch { toast.error("Failed to remove command"); }
  };

  const handleChannelToggle = async (type: "excluded_channels" | "target_channels", channelId: string, add: boolean) => {
    try {
      const key = add ? `add_${type === "excluded_channels" ? "excluded" : "target"}_channel` : `remove_${type === "excluded_channels" ? "excluded" : "target"}_channel`;
      const result = await api.updateAntiSpamPlus(guildId, { [key]: channelId });
      setConfig((prev: any) => ({ ...prev, [type]: result[type] }));
    } catch { toast.error("Failed to update channel"); }
  };

  const updateField = (field: string, value: any) => {
    setConfig((prev: any) => ({ ...prev, [field]: value }));
  };

  const toggleDeleteMessages = async (value: boolean) => {
    updateField("delete_messages", value);
    try {
      const result = await api.updateAntiSpamPlus(guildId, { delete_messages: value });
      setConfig((prev: any) => ({ ...prev, ...result }));
      toast.success(value ? "Message deletion enabled" : "Message deletion disabled");
    } catch (err) {
      toast.error("Failed to update message deletion");
      console.error(err);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
      <div className="lg:col-span-3 space-y-6">
        <div className="bg-[#111111] border border-[#1A1A1A] rounded-[32px] shadow-2xl p-8 space-y-10 relative">

          {/* Adaptive Heat Protection */}
          <div className="space-y-6">
            <div className="flex items-center justify-between p-4 bg-gradient-to-r from-orange-500/10 to-transparent rounded-[6px] border border-orange-500/20">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-orange-500/10 text-orange-400"><Flame className="h-5 w-5" /></div>
                <div>
                  <h4 className="font-bold text-slate-50 text-sm">Adaptive Heat Protection</h4>
                  <p className="text-xs text-neutral-400">Scores message speed, repetition, mentions, links, emoji and attachment floods</p>
                </div>
              </div>
              <Switch checked={config.heat_enabled ?? true} onCheckedChange={(value) => updateField("heat_enabled", value)} />
            </div>

            {config.heat_enabled !== false && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pl-4 border-l-2 border-orange-500/20">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Heat threshold</label>
                  <Input type="number" min={30} max={300} value={config.heat_threshold ?? 100} onChange={(e) => updateField("heat_threshold", parseInt(e.target.value) || 100)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Decay / second</label>
                  <Input type="number" min={0.1} max={50} step={0.5} value={config.heat_decay_per_second ?? 6} onChange={(e) => updateField("heat_decay_per_second", parseFloat(e.target.value) || 6)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Timeout (minutes)</label>
                  <Input type="number" min={1} max={10080} value={config.heat_timeout_minutes ?? 10} onChange={(e) => updateField("heat_timeout_minutes", parseInt(e.target.value) || 10)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Panic duration (minutes)</label>
                  <Input type="number" min={1} max={1440} value={config.panic_minutes ?? 10} onChange={(e) => updateField("panic_minutes", parseInt(e.target.value) || 10)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Raid users</label>
                  <Input type="number" min={2} max={50} value={config.raid_trigger_users ?? 3} onChange={(e) => updateField("raid_trigger_users", parseInt(e.target.value) || 3)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Raid window (seconds)</label>
                  <Input type="number" min={5} max={300} value={config.raid_window_seconds ?? 30} onChange={(e) => updateField("raid_window_seconds", parseInt(e.target.value) || 30)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="col-span-2 flex items-center justify-between p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]">
                  <div>
                    <p className="text-xs font-bold text-slate-100">Delete heated messages</p>
                    <p className="text-[11px] text-neutral-500">Removes suspicious messages before timeout</p>
                  </div>
                  <Switch checked={config.heat_delete_messages ?? true} onCheckedChange={(value) => updateField("heat_delete_messages", value)} />
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-[#1A1A1A]" />

          {/* Join Gate */}
          <div className="space-y-6">
            <div className="flex items-center justify-between p-4 bg-[#131313] rounded-[6px] border border-[#1A1A1A]">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-xl bg-emerald-500/10 text-emerald-400"><UserPlus className="h-5 w-5" /></div>
                <div>
                  <h4 className="font-bold text-slate-50 text-sm">Join Gate</h4>
                  <p className="text-xs text-neutral-400">Reject risky new accounts and unauthorized bots before they enter</p>
                </div>
              </div>
              <Switch checked={config.join_gate_enabled ?? false} onCheckedChange={(value) => updateField("join_gate_enabled", value)} />
            </div>
            {config.join_gate_enabled && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pl-4 border-l-2 border-emerald-500/20">
                <div className="space-y-2">
                  <label className="text-xs font-bold text-neutral-400">Minimum account age (hours)</label>
                  <Input type="number" min={1} max={8760} value={config.min_account_age_hours ?? 24} onChange={(e) => updateField("min_account_age_hours", parseInt(e.target.value) || 24)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
                </div>
                <div className="flex items-center justify-between p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]">
                  <span className="text-xs font-bold text-neutral-300">Require avatar</span>
                  <Switch checked={config.block_no_avatar ?? false} onCheckedChange={(value) => updateField("block_no_avatar", value)} />
                </div>
                <div className="flex items-center justify-between p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]">
                  <span className="text-xs font-bold text-neutral-300">Block unverified bots</span>
                  <Switch checked={config.block_unverified_bots ?? true} onCheckedChange={(value) => updateField("block_unverified_bots", value)} />
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-[#1A1A1A]" />

          {/* Message Deletion Toggle */}
          <div className="flex items-center justify-between p-4 bg-[#131313] rounded-[6px] border border-[#1A1A1A]">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-red-500/10 text-red-400"><MessageSquare className="h-5 w-5" /></div>
              <div>
                <h4 className="font-bold text-slate-50 text-sm">Message Deletion</h4>
                <p className="text-xs text-neutral-400">Delete messages from target users or matching commands</p>
              </div>
            </div>
            <Switch checked={config.delete_messages} onCheckedChange={toggleDeleteMessages} />
          </div>

          {config.delete_messages && (
            <div className="space-y-8 pl-4 border-l-2 border-[#1A1A1A]">

              {/* Delete Delay */}
              <div className="flex items-center gap-4">
                <label className="text-xs font-bold text-neutral-400 w-32">Delete Delay (s)</label>
                <Input type="number" min={1} max={60} value={config.delete_delay} onChange={(e) => updateField("delete_delay", parseInt(e.target.value) || 8)} className="w-24 bg-[#0F0F0F] border-[#1A1A1A] h-10" />
              </div>

              {/* Target Users */}
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-red-500/10 text-red-400"><UserX className="h-4 w-4" /></div>
                  <h4 className="font-bold text-slate-50 text-sm">Target Users</h4>
                </div>
                <div className="flex gap-2">
                  <Input placeholder="Discord User ID" value={newUserId} onChange={(e) => setNewUserId(e.target.value)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10 flex-1" />
                  <Button size="sm" onClick={addTargetUser} variant="secondary"><Plus className="h-4 w-4" /></Button>
                </div>
                <div className="flex flex-wrap gap-2 min-h-[40px] p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]/50">
                  {config.target_users?.length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No target users</span>
                  ) : (
                    config.target_users?.map((uid: string) => (
                      <div key={uid} className="flex items-center gap-2 bg-[#1A1A1A] border border-neutral-700/50 px-3 py-1.5 rounded-lg text-sm">
                        <span className="text-neutral-200 font-mono text-xs">{uid}</span>
                        <button onClick={() => removeTargetUser(uid)} className="text-neutral-500 hover:text-red-400 transition-colors"><Trash2 className="h-3 w-3" /></button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Blocked Commands */}
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-orange-500/10 text-orange-400"><Command className="h-4 w-4" /></div>
                  <h4 className="font-bold text-slate-50 text-sm">Blocked Commands</h4>
                </div>
                <div className="flex gap-2">
                  <Input placeholder="e.g. !play" value={newCommand} onChange={(e) => setNewCommand(e.target.value)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10 flex-1" />
                  <Button size="sm" onClick={addBlockedCommand} variant="secondary"><Plus className="h-4 w-4" /></Button>
                </div>
                <div className="flex flex-wrap gap-2 min-h-[40px] p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]/50">
                  {config.blocked_commands?.length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No blocked commands</span>
                  ) : (
                    config.blocked_commands?.map((cmd: string) => (
                      <div key={cmd} className="flex items-center gap-2 bg-[#1A1A1A] border border-neutral-700/50 px-3 py-1.5 rounded-lg text-sm">
                        <span className="text-neutral-200 font-mono text-xs">{cmd}</span>
                        <button onClick={() => removeBlockedCommand(cmd)} className="text-neutral-500 hover:text-red-400 transition-colors"><Trash2 className="h-3 w-3" /></button>
                      </div>
                    ))
                  )}
                </div>
              </div>

              {/* Excluded Channels */}
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-neutral-500/10 text-neutral-400"><Hash className="h-4 w-4" /></div>
                  <h4 className="font-bold text-slate-50 text-sm">Excluded Channels</h4>
                </div>
                <Select value="" onValueChange={(val) => handleChannelToggle("excluded_channels", val, true)}>
                  <SelectTrigger className="w-full h-10 bg-[#0F0F0F] border-[#1A1A1A]">
                    <SelectValue placeholder="Add channel to exclude..." />
                  </SelectTrigger>
                  <SelectContent className="bg-[#111111] border-[#1A1A1A] max-h-[300px]">
                    {channels.filter((c: any) => !(config.excluded_channels || []).includes(c.id)).map((c: any) => (
                      <SelectItem key={c.id} value={c.id} className="focus:bg-[#1A1A1A]">#{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex flex-wrap gap-2 min-h-[40px] p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]/50">
                  {(config.excluded_channels || []).length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No excluded channels</span>
                  ) : (
                    config.excluded_channels?.map((chId: string) => {
                      const ch = channels.find((c: any) => c.id === chId);
                      return (
                        <div key={chId} className="flex items-center gap-2 bg-[#1A1A1A] border border-neutral-700/50 px-3 py-1.5 rounded-lg text-sm">
                          <span className="text-neutral-200">#{ch?.name || chId}</span>
                          <button onClick={() => handleChannelToggle("excluded_channels", chId, false)} className="text-neutral-500 hover:text-red-400 transition-colors"><Trash2 className="h-3 w-3" /></button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Divider */}
          <div className="border-t border-[#1A1A1A]" />

          {/* Reaction Anti-Spam */}
          <div className="space-y-6">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-yellow-500/10 text-yellow-400"><SmilePlus className="h-5 w-5" /></div>
              <div>
                <h4 className="font-bold text-slate-50 text-base">Reaction Anti-Spam</h4>
                <p className="text-xs text-neutral-400">Detect and punish rapid reaction spam in monitored channels</p>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-2">
                <label className="text-xs font-bold text-neutral-400">Limit (msgs)</label>
                <Input type="number" min={1} max={50} value={config.re_limit} onChange={(e) => updateField("re_limit", parseInt(e.target.value) || 5)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold text-neutral-400">Window (s)</label>
                <Input type="number" min={1} max={300} value={config.re_window} onChange={(e) => updateField("re_window", parseInt(e.target.value) || 30)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold text-neutral-400">Cooldown (s)</label>
                <Input type="number" min={1} max={300} value={config.re_cooldown} onChange={(e) => updateField("re_cooldown", parseInt(e.target.value) || 20)} className="bg-[#0F0F0F] border-[#1A1A1A] h-10" />
              </div>
            </div>

            {/* Target Channels for Reaction Spam */}
            <div className="space-y-4">
              <h4 className="text-sm font-bold text-slate-50 flex items-center gap-2"><Users className="h-4 w-4 text-yellow-400" /> Monitored Channels</h4>
<Select value="" onValueChange={(val) => handleChannelToggle("target_channels", val, true)}>
                  <SelectTrigger className="w-full h-10 bg-[#0F0F0F] border-[#1A1A1A]">
                    <SelectValue placeholder="Add channel to monitor..." />
                  </SelectTrigger>
                  <SelectContent className="bg-[#111111] border-[#1A1A1A] max-h-[300px]">
                    {channels.filter((c: any) => !(config.target_channels || []).includes(c.id)).map((c: any) => (
                      <SelectItem key={c.id} value={c.id} className="focus:bg-[#1A1A1A]">#{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex flex-wrap gap-2 min-h-[40px] p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]/50">
                  {(config.target_channels || []).length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No channels monitored</span>
                  ) : (
                    config.target_channels?.map((chId: string) => {
                      const ch = channels.find((c: any) => c.id === chId);
                    return (
                      <div key={chId} className="flex items-center gap-2 bg-[#1A1A1A] border border-neutral-700/50 px-3 py-1.5 rounded-lg text-sm">
                        <span className="text-neutral-200">#{ch?.name || chId}</span>
                        <button onClick={() => handleChannelToggle("target_channels", chId, false)} className="text-neutral-500 hover:text-red-400 transition-colors"><Trash2 className="h-3 w-3" /></button>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          </div>

          {/* Save Button */}
          <div className="pt-6 border-t border-[#1A1A1A]">
            <Button
              onClick={handleSave}
              disabled={saving}
              className="w-full h-14 text-base font-bold gap-3 shadow-lg shadow-primary/20 hover:shadow-primary/30 active:scale-[0.98] transition-all"
            >
              {saving ? <RefreshCcw className="h-5 w-5 animate-spin" /> : <Save className="h-5 w-5" />}
              Save Anti-Spam+ Settings
            </Button>
          </div>

        </div>
      </div>

      {/* Sidebar */}
      <div className="space-y-6">
        <div className="bg-gradient-to-br from-primary/10 to-transparent border border-primary/20 rounded-[6px] p-6 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-[0.03] group-hover:scale-110 transition-transform">
            <ShieldCheck className="h-32 w-32 text-primary" />
          </div>
          <div className="flex items-center gap-2 mb-4">
            <Info className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold text-slate-50">How It Works</h3>
          </div>
          <ul className="text-xs text-neutral-500 space-y-2">
            <li>• Heat rises from suspicious behavior and decays during normal use.</li>
            <li>• Repeat offenders receive progressively longer timeouts.</li>
            <li>• Multi-user raids trigger temporary panic protection.</li>
            <li>• Join Gate can reject risky new accounts and bots.</li>
          </ul>
        </div>

        {/* Sync Emoji Button */}
        <div className="bg-[#131313] border border-[#1A1A1A] rounded-[6px] p-6">
          <div className="flex items-center gap-2 mb-3">
            <SmilePlus className="h-4 w-4 text-yellow-400" />
            <h3 className="text-sm font-bold text-slate-50">Emoji Sync</h3>
          </div>
          <p className="text-xs text-neutral-500 mb-4">Emojis are managed directly in emoji.py on GitHub.</p>
        </div>
      </div>
    </div>
  );
}
