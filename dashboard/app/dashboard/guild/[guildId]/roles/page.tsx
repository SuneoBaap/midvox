import { Layers3 } from "lucide-react";
import { api } from "@/lib/api";
import { RoleManagerForm } from "@/components/dashboard/role-manager-form";

export default async function RolesPage({ params }: { params: { guildId: string } }) {
  const roles = await api.getRoles(params.guildId);
  return (
    <div className="mx-auto max-w-7xl space-y-7 animate-in fade-in slide-in-from-bottom-2 duration-500">
      <div>
        <h2 className="flex items-center gap-2 text-2xl font-bold text-[var(--panel-ink)]">
          <Layers3 className="h-6 w-6 text-primary" /> Role Creator
        </h2>
        <p className="mt-1 text-[var(--panel-muted)]">Create Discord roles from presets, customize every permission, and control their exact hierarchy position.</p>
      </div>
      <RoleManagerForm guildId={params.guildId} initialRoles={roles} />
    </div>
  );
}
