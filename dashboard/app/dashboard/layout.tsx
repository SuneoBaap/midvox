"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, Server, ShieldCheck, Ticket, BarChart4, Settings, Layers3,
  Menu, X, Bell, User, Search, ChevronRight, Sparkles, LogOut,
  LifeBuoy, ChevronDown, Shield, Download, Zap, Moon, Sun, MessageSquare,
} from "lucide-react";
import { useSession, signIn, signOut } from "next-auth/react";
import { cn, isAdmin } from "@/lib/utils";
import { api } from "@/lib/api";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME || "MidVox";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);
  const [globalNotification, setGlobalNotification] = useState<string | null>(null);
  const [darkMode, setDarkMode] = useState(false);
  const pathname = usePathname();
  const { data: session, status } = useSession();
  const bellRef = useRef<HTMLDivElement>(null);
  const profileRef = useRef<HTMLDivElement>(null);
  const authRedirectStarted = useRef(false);

  useEffect(() => {
    const isDark = window.localStorage.getItem("midvox-theme") === "dark";
    setDarkMode(isDark);
    document.documentElement.classList.toggle("theme-dark", isDark);
  }, []);

  const toggleTheme = () => {
    const nextMode = !darkMode;
    setDarkMode(nextMode);
    window.localStorage.setItem("midvox-theme", nextMode ? "dark" : "light");
    document.documentElement.classList.toggle("theme-dark", nextMode);
  };

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node;
      if (bellRef.current && !bellRef.current.contains(target)) setIsNotificationsOpen(false);
      if (profileRef.current && !profileRef.current.contains(target)) setIsProfileOpen(false);
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  useEffect(() => {
    setIsSidebarOpen(false);
    setIsProfileOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (status !== "unauthenticated" || authRedirectStarted.current) return;

    authRedirectStarted.current = true;
    const callbackUrl = pathname;
    void signIn("discord", { callbackUrl });
  }, [pathname, status]);

  useEffect(() => {
    if (status !== "authenticated") return;

    const fetchNotification = async () => {
      try {
        const config = await api.getAdminConfig();
        setGlobalNotification(config.global_notification);
      } catch {}
    };
    fetchNotification();
  }, [status]);

  if (status === "loading" || status === "unauthenticated") {
    return (
      <div className="panel-shell flex min-h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="panel-brand-mark h-11 w-11 text-xl">m</div>
          <p className="animate-pulse text-[10px] font-semibold uppercase tracking-[0.24em] text-[var(--panel-muted)]">
            Authenticating
          </p>
        </div>
      </div>
    );
  }

  const match = pathname.match(/\/dashboard\/guild\/([^/]+)/);
  const currentGuildId = match ? match[1] : null;

  const allSidebarItems = currentGuildId
    ? [
        { name: "Overview", href: `/dashboard/guild/${currentGuildId}`, icon: LayoutDashboard },
        {
          name: "Security",
          items: [
            { name: "Anti-Nuke", href: `/dashboard/guild/${currentGuildId}/antinuke`, icon: ShieldCheck },
            { name: "Automod", href: `/dashboard/guild/${currentGuildId}/automod`, icon: ShieldCheck },
            { name: "Message Deleter", href: `/dashboard/guild/${currentGuildId}/antispamplus`, icon: MessageSquare },
            { name: "Verification", href: `/dashboard/guild/${currentGuildId}/verification`, icon: User },
          ],
        },
        {
          name: "Engagement",
          items: [
            { name: "Welcome", href: `/dashboard/guild/${currentGuildId}/welcome`, icon: Bell },
            { name: "Leveling", href: `/dashboard/guild/${currentGuildId}/leveling`, icon: BarChart4 },
            { name: "Vanity Roles", href: `/dashboard/guild/${currentGuildId}/vanityroles`, icon: Sparkles },
            { name: "Auto Role", href: `/dashboard/guild/${currentGuildId}/autorole`, icon: User },
            { name: "Auto React", href: `/dashboard/guild/${currentGuildId}/autoreact`, icon: Zap },
            { name: "Reaction Roles", href: `/dashboard/guild/${currentGuildId}/reactionroles`, icon: Zap },
            { name: "Join DM", href: `/dashboard/guild/${currentGuildId}/joindm`, icon: User },
            { name: "Invites", href: `/dashboard/guild/${currentGuildId}/invites`, icon: Server },
            { name: "Tracking", href: `/dashboard/guild/${currentGuildId}/tracking`, icon: BarChart4 },
          ],
        },
        {
          name: "Media",
          items: [
            { name: "Insta Downloader", href: `/dashboard/guild/${currentGuildId}/instadl`, icon: Download },
          ],
        },
        {
          name: "Utility",
          items: [
            { name: "Tickets", href: `/dashboard/guild/${currentGuildId}/tickets`, icon: Ticket },
            { name: "Join to Create", href: `/dashboard/guild/${currentGuildId}/j2c`, icon: Settings },
            { name: "Custom Roles", href: `/dashboard/guild/${currentGuildId}/customroles`, icon: ShieldCheck },
            { name: "Role Creator", href: `/dashboard/guild/${currentGuildId}/roles`, icon: Layers3 },
            { name: "Voice Role", href: `/dashboard/guild/${currentGuildId}/invcrole`, icon: Settings },
          ],
        },
        { name: "Settings", href: `/dashboard/guild/${currentGuildId}/settings`, icon: Settings },
        { name: "Back to Servers", href: "/dashboard/guilds", icon: Server },
      ]
    : [
        { name: "Dashboard", href: "/dashboard", icon: LayoutDashboard },
        { name: "Servers", href: "/dashboard/guilds", icon: Server },
        ...(isAdmin(session?.user?.id)
          ? [{ name: "Admin Panel", href: "/dashboard/admin", icon: Shield }]
          : []),
      ];

  let mainSidebarItems = allSidebarItems;
  let backLinkItem: any = null;
  if (currentGuildId) {
    mainSidebarItems = allSidebarItems.filter((item) => item.name !== "Back to Servers");
    backLinkItem = allSidebarItems.find((item) => item.name === "Back to Servers");
  }
  const BackLinkIcon = backLinkItem?.icon || Server;

  const NavLink = ({ item }: { item: any }) => {
    const isActive = pathname === item.href;
    return (
      <Link
        href={item.href}
        className={cn(
          "panel-nav-link group relative flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[12px] font-semibold transition-all duration-150",
          isActive && "is-active"
        )}
      >
        <item.icon className="h-3.5 w-3.5 shrink-0" />
        {item.name}
        {isActive && <ChevronRight className="ml-auto h-3 w-3 opacity-50" />}
      </Link>
    );
  };

  const SidebarContent = () => (
    <>
      {/* Logo header */}
      <div className="panel-sidebar-header flex h-16 shrink-0 items-center px-4">
        <Link href="/" className="flex items-center gap-2.5" aria-label={`${BRAND} homepage`}>
          <div className="panel-brand-mark">m</div>
          <div>
            <p className="panel-brand-name text-[14px] font-extrabold leading-none">
              {BRAND.toLowerCase()}
            </p>
            <p className="mt-1 text-[8px] font-bold uppercase tracking-[0.2em] text-[var(--panel-accent-deep)]">
              Control panel
            </p>
          </div>
        </Link>
        <button
          className="panel-icon-button ml-auto lg:hidden"
          onClick={() => setIsSidebarOpen(false)}
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Nav */}
      <nav className="no-scrollbar flex-1 space-y-4 overflow-y-auto p-3">
        {mainSidebarItems.map((item: any) => {
          if (item.items) {
            return (
              <div key={item.name}>
                <p className="panel-nav-label mb-1.5 px-3 text-[9px] font-bold uppercase tracking-[0.18em]">
                  {item.name}
                </p>
                <div className="space-y-0.5">
                  {item.items.map((sub: any) => <NavLink key={sub.name} item={sub} />)}
                </div>
              </div>
            );
          }
          return <NavLink key={item.name} item={item} />;
        })}

        {backLinkItem && (
          <div className="border-t border-[var(--panel-line)] pt-3">
            <Link
              href={backLinkItem.href}
              className="panel-nav-link group flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[12px] font-semibold transition-all"
            >
              <BackLinkIcon className="h-3.5 w-3.5 shrink-0" />
              {backLinkItem.name}
            </Link>
          </div>
        )}
      </nav>

      {/* User profile */}
      <div className="shrink-0 border-t border-[var(--panel-line)] p-3">
        <div className="panel-user-card flex items-center gap-2.5 rounded-2xl px-3 py-2.5">
          <div className="relative h-8 w-8 rounded-[4px] overflow-hidden border border-[#2A2A2A] shrink-0">
            {session?.user?.image ? (
              <Image src={session.user.image!} alt="Avatar" fill className="object-cover" />
            ) : (
              <div className="h-full w-full bg-[#1A1A1A] flex items-center justify-center">
                <User className="h-4 w-4 text-[#555]" />
              </div>
            )}
          </div>
          <div className="overflow-hidden">
            <p className="truncate text-xs font-semibold leading-none text-[var(--panel-ink)]">
              {session?.user?.name || "Admin"}
            </p>
            <p className="text-[8px] font-mono uppercase tracking-[0.2em] text-[#22C55E] mt-1 flex items-center gap-1">
              <span className="w-1 h-1 rounded-full bg-[#22C55E] inline-block" />
              Online
            </p>
          </div>
          <button
            onClick={() => signOut({ callbackUrl: "/" })}
            className="ml-auto rounded-lg p-1.5 text-[var(--panel-muted)] transition-all hover:bg-red-500/10 hover:text-red-500"
            title="Sign out"
          >
            <LogOut className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="panel-shell min-h-screen">
      {/* Mobile overlay */}
      <AnimatePresence>
        {isSidebarOpen && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/70 lg:hidden"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside className={cn(
        "panel-sidebar fixed bottom-0 left-0 top-0 z-50 flex w-60 flex-col transition-transform duration-200 lg:translate-x-0",
        isSidebarOpen ? "translate-x-0" : "-translate-x-full"
      )}>
        <SidebarContent />
      </aside>

      {/* Main */}
      <div className="lg:pl-60 flex flex-col min-h-screen">
        {/* Topbar */}
        <header className="panel-topbar sticky top-0 z-30 flex h-16 items-center px-4 backdrop-blur-xl lg:px-7">
          <button
            className="panel-icon-button mr-3 lg:hidden"
            onClick={() => setIsSidebarOpen(true)}
          >
            <Menu className="h-4 w-4" />
          </button>

          {/* Search */}
          <div className="hidden md:flex items-center relative">
            <Search className="absolute left-3 h-3.5 w-3.5 text-[#444]" />
            <input
              type="text"
              placeholder="search..."
              className="panel-search w-64 rounded-full py-2 pl-9 pr-3 text-xs transition-all focus:outline-none"
            />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button onClick={toggleTheme} className="panel-icon-button" aria-label={darkMode ? "Use light theme" : "Use dark theme"}>
              {darkMode ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* Bell */}
            <div className="relative" ref={bellRef}>
              <button
                onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
                className="panel-icon-button relative"
              >
                <Bell className="h-4 w-4" />
                {globalNotification && (
                  <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-[var(--panel-accent)]" />
                )}
              </button>
              <AnimatePresence>
                {isNotificationsOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 6 }} transition={{ duration: 0.12 }}
                    className="panel-popover absolute right-0 z-20 mt-2 w-72 rounded-2xl p-3"
                  >
                    <div className="flex items-center justify-between mb-2 pb-2 border-b border-[#1F1F1F]">
                      <p className="text-[9px] font-mono uppercase tracking-[0.2em] text-[#555]">Broadcasts</p>
                      <button onClick={() => setGlobalNotification(null)} className="text-[9px] font-mono uppercase text-[#F59E0B]/60 hover:text-[#F59E0B] transition-colors">Clear</button>
                    </div>
                    {globalNotification ? (
                      <div className="bg-[rgba(245,158,11,0.05)] border border-[#F59E0B]/20 rounded-[4px] p-3">
                        <div className="flex items-center gap-2 mb-1.5">
                          <Sparkles className="h-3 w-3 text-[#F59E0B]" />
                          <span className="text-[9px] font-mono uppercase tracking-widest text-[#F59E0B]">System</span>
                        </div>
                        <p className="text-xs text-[#BBB] leading-relaxed">{globalNotification}</p>
                      </div>
                    ) : (
                      <div className="py-6 flex flex-col items-center gap-2">
                        <Bell className="h-5 w-5 text-[#333]" />
                        <p className="text-xs font-mono text-[#555]">No active broadcasts</p>
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            <div className="h-5 w-px bg-[#1F1F1F] hidden sm:block" />

            {/* Profile */}
            <div className="relative" ref={profileRef}>
              <button
                onClick={() => setIsProfileOpen(!isProfileOpen)}
                className="panel-profile-button flex items-center gap-2 rounded-full p-1.5 transition-all"
              >
                <div className="relative h-7 w-7 rounded-[4px] overflow-hidden border border-[#2A2A2A]">
                  {session?.user?.image ? (
                    <Image src={session.user.image!} alt="Avatar" fill className="object-cover" />
                  ) : (
                    <div className="h-full w-full bg-[#1A1A1A] flex items-center justify-center">
                      <User className="h-3.5 w-3.5 text-[#555]" />
                    </div>
                  )}
                </div>
                <span className="hidden text-xs font-semibold text-[var(--panel-ink)] sm:block">
                  {session?.user?.name?.split(" ")[0] || "Admin"}
                </span>
                <ChevronDown className={cn("h-3 w-3 text-[#555] hidden sm:block transition-transform", isProfileOpen && "rotate-180")} />
              </button>

              <AnimatePresence>
                {isProfileOpen && (
                  <motion.div
                    initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 6 }} transition={{ duration: 0.12 }}
                    className="panel-popover absolute right-0 z-20 mt-2 w-48 rounded-2xl p-1.5"
                  >
                    <div className="px-3 py-2 border-b border-[#1F1F1F] mb-1">
                      <p className="text-[9px] font-mono uppercase tracking-[0.2em] text-[#555] mb-0.5">Signed in as</p>
                      <p className="text-xs font-semibold text-[#DDD] truncate">{session?.user?.name || "Administrator"}</p>
                    </div>
                    <button className="w-full flex items-center gap-2.5 px-3 py-2 rounded-[4px] text-xs font-mono font-medium text-[#777] hover:bg-[#1A1A1A] hover:text-[#CCC] transition-all">
                      <LifeBuoy className="h-3.5 w-3.5" />
                      Support
                    </button>
                    <button
                      onClick={() => signOut({ callbackUrl: "/" })}
                      className="w-full flex items-center gap-2.5 px-3 py-2 rounded-[4px] text-xs font-mono font-medium text-[#EF4444]/70 hover:bg-[rgba(239,68,68,0.08)] hover:text-[#EF4444] transition-all"
                    >
                      <LogOut className="h-3.5 w-3.5" />
                      Sign Out
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="panel-main flex-1 p-4 lg:p-7">
          <AnimatePresence mode="wait">
            <motion.div
              key={pathname}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <div className="max-w-[1400px] mx-auto">{children}</div>
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
