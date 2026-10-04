"use client";

import React, { useState, useEffect, useRef } from "react";
import { Instagram, Save, RefreshCcw, Trash2, Info, Plus, Download, Hash } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

interface InstaDLFormProps {
  initialConfig: any;
  channels: any[];
  guildId: string;
}

export function InstaDLForm({ initialConfig, channels, guildId }: InstaDLFormProps) {
  const [config, setConfig] = useState<any>(initialConfig);
  const [saving, setSaving] = useState(false);
  const [channelUpdating, setChannelUpdating] = useState(false);
  const channelMutationPending = useRef(false);

  useEffect(() => {
    setConfig(initialConfig);
  }, [initialConfig]);

  const handleSave = async () => {
    setSaving(true);
    const data: any = {
      enabled: config.enabled,
    };
    const promise = api.updateInstaDL(guildId, data);
    toast.promise(promise, {
      loading: "Saving Media Downloader configuration...",
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

  const toggleEnabled = async (value: boolean) => {
    setConfig((prev: any) => ({ ...prev, enabled: value }));
    try {
      const result = await api.updateInstaDL(guildId, { enabled: value });
      setConfig((prev: any) => ({ ...prev, ...result }));
      toast.success(value ? "Media Downloader enabled" : "Media Downloader disabled");
    } catch (err) {
      toast.error("Failed to update status");
      console.error(err);
    }
  };

  const addChannel = async (channelId: string) => {
    channelId = String(channelId);
    if (!channelId || channelMutationPending.current) return;

    channelMutationPending.current = true;
    setChannelUpdating(true);
    setConfig((prev: any) => ({
      ...prev,
      channels: Array.from(new Set([...(prev.channels || []).map(String), channelId])),
    }));

    try {
      const result = await api.updateInstaDL(guildId, { add_channel: channelId });
      setConfig((prev: any) => ({
        ...prev,
        ...result,
        channels: Array.from(new Set([...(result.channels || []).map(String), channelId])),
      }));
      toast.success("Channel added");
    } catch {
      setConfig((prev: any) => ({
        ...prev,
        channels: (prev.channels || []).map(String).filter((id: string) => id !== channelId),
      }));
      toast.error("Failed to add channel");
    } finally {
      channelMutationPending.current = false;
      setChannelUpdating(false);
    }
  };

  const removeChannel = async (channelId: string) => {
    channelId = String(channelId);
    if (channelMutationPending.current) return;

    channelMutationPending.current = true;
    setChannelUpdating(true);
    setConfig((prev: any) => ({
      ...prev,
      channels: (prev.channels || []).map(String).filter((id: string) => id !== channelId),
    }));

    try {
      const result = await api.updateInstaDL(guildId, { remove_channel: channelId });
      setConfig((prev: any) => ({
        ...prev,
        ...result,
        channels: (result.channels || []).map(String).filter((id: string) => id !== channelId),
      }));
      toast.success("Channel removed");
    } catch {
      setConfig((prev: any) => ({
        ...prev,
        channels: Array.from(new Set([...(prev.channels || []).map(String), channelId])),
      }));
      toast.error("Failed to remove channel");
    } finally {
      channelMutationPending.current = false;
      setChannelUpdating(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
      <div className="lg:col-span-3 space-y-6">
        <div className="bg-[#111111] border border-[#1A1A1A] rounded-[32px] shadow-2xl p-8 space-y-10 relative">

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between p-4 bg-[#131313] rounded-[6px] border border-[#1A1A1A]">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-primary/10 text-primary"><Download className="h-5 w-5" /></div>
              <div>
                <h4 className="font-bold text-slate-50 text-sm">Enabled</h4>
                <p className="text-xs text-neutral-400">Watch selected channels for Instagram Reels &amp; YouTube Shorts</p>
              </div>
            </div>
            <Switch checked={config.enabled} onCheckedChange={toggleEnabled} />
          </div>

          {config.enabled && (
            <div className="space-y-8 pl-4 border-l-2 border-[#1A1A1A]">

              {/* Auto-Delete Notice */}
              <div className="flex items-center justify-between p-4 bg-[#131313] rounded-[6px] border border-[#1A1A1A]">
                <div className="flex items-center gap-3">
                  <div className="p-2.5 rounded-xl bg-red-500/10 text-red-400"><Trash2 className="h-5 w-5" /></div>
                  <div>
                    <h4 className="font-bold text-slate-50 text-sm">Original Link Removed</h4>
                    <p className="text-xs text-neutral-400">The posted link (and its embed) is deleted automatically after the media is reposted</p>
                  </div>
                </div>
              </div>

              {/* Monitored Channels */}
              <div className="space-y-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10 text-primary"><Hash className="h-4 w-4" /></div>
                  <h4 className="font-bold text-slate-50 text-sm">Monitored Channels</h4>
                </div>
                <Select value="" onValueChange={addChannel} disabled={channelUpdating}>
                  <SelectTrigger disabled={channelUpdating} className="w-full h-10 bg-[#0F0F0F] border-[#1A1A1A]">
                    <SelectValue placeholder={channelUpdating ? "Updating channels..." : "Add channel to monitor..."} />
                  </SelectTrigger>
                  <SelectContent className="bg-[#111111] border-[#1A1A1A] max-h-[300px]">
                    {channels.filter((c: any) => !(config.channels || []).includes(c.id)).map((c: any) => (
                      <SelectItem key={c.id} value={c.id} className="focus:bg-[#1A1A1A]">#{c.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="flex flex-wrap gap-2 min-h-[40px] p-3 bg-[#131313] rounded-xl border border-[#1A1A1A]/50">
                  {(config.channels || []).length === 0 ? (
                    <span className="text-xs text-neutral-600 italic">No channels monitored</span>
                  ) : (
                    config.channels?.map((chId: string) => {
                      const ch = channels.find((c: any) => c.id === chId);
                      return (
                        <div key={chId} className="flex items-center gap-2 bg-[#1A1A1A] border border-neutral-700/50 px-3 py-1.5 rounded-lg text-sm">
                          <span className="text-neutral-200">#{ch?.name || chId}</span>
                          <button disabled={channelUpdating} onClick={() => removeChannel(chId)} className="text-neutral-500 hover:text-red-400 transition-colors disabled:cursor-not-allowed disabled:opacity-40"><Trash2 className="h-3 w-3" /></button>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Save Button */}
          <div className="pt-6 border-t border-[#1A1A1A]">
            <Button
              onClick={handleSave}
              disabled={saving}
              className="w-full h-14 text-base font-bold gap-3 shadow-lg shadow-primary/20 hover:shadow-primary/30 active:scale-[0.98] transition-all"
            >
              {saving ? <RefreshCcw className="h-5 w-5 animate-spin" /> : <Save className="h-5 w-5" />}
              Save Media Downloader Settings
            </Button>
          </div>

        </div>
      </div>

      {/* Sidebar */}
      <div className="space-y-6">
        <div className="bg-gradient-to-br from-primary/10 to-transparent border border-primary/20 rounded-[6px] p-6 relative overflow-hidden group">
          <div className="absolute -right-4 -top-4 opacity-[0.03] group-hover:scale-110 transition-transform">
            <Instagram className="h-32 w-32 text-primary" />
          </div>
          <div className="flex items-center gap-2 mb-4">
            <Info className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold text-slate-50">How It Works</h3>
          </div>
          <ul className="text-xs text-neutral-500 space-y-2">
            <li>â€¢ Instagram Reels &amp; YouTube Shorts are downloaded automatically.</li>
            <li>â€¢ Media is reposted inline in the channel.</li>
            <li>â€¢ The original link message is deleted so no embed is left behind.</li>
            <li>â€¢ Files are capped at 24MB for Discord limits.</li>
            <li>â€¢ Only monitored channels are watched.</li>
          </ul>
        </div>

        <div className="bg-[#131313] border border-[#1A1A1A] rounded-[6px] p-6">
          <div className="flex items-center gap-2 mb-3">
            <Plus className="h-4 w-4 text-primary" />
            <h3 className="text-sm font-bold text-slate-50">Supported Links</h3>
          </div>
          <p className="text-xs text-neutral-500 mb-2">instagram.com reels, posts, stories, instagr.am short links &amp; youtube.com/shorts links.</p>
        </div>
      </div>
    </div>
  );
}
