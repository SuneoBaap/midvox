"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  BarChart3,
  Bell,
  Check,
  ChevronRight,
  Command,
  LayoutTemplate,
  Lock,
  Moon,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
  Ticket,
  Users,
  Zap,
} from "lucide-react";
import { motion } from "framer-motion";
import { signIn, useSession } from "next-auth/react";
import { useRouter } from "next/navigation";

const BRAND = process.env.NEXT_PUBLIC_BRAND_NAME || "MidVox";
const BOT_INVITE = "/dashboard";

const DISCOVERY_ITEMS = [
  { icon: ShieldCheck, title: "Protect", description: "Keep bad actors out before they become a problem.", tint: "sage" },
  { icon: Sparkles, title: "Welcome", description: "Turn a new member into part of the community.", tint: "lilac" },
  { icon: Ticket, title: "Support", description: "Give every question a place to land and resolve.", tint: "peach" },
  { icon: BarChart3, title: "Understand", description: "See the patterns that make your community work.", tint: "sky" },
];

const FEATURE_BOARDS = [
  {
    eyebrow: "Security",
    title: "Let the quiet work happen automatically.",
    body: "Thoughtful defaults and configurable rules protect your server without putting friction in front of good members.",
    label: "AutoMod workspace",
    icon: ShieldCheck,
    kind: "moderation",
  },
  {
    eyebrow: "Community",
    title: "Give every member a reason to come back.",
    body: "Build better rituals around welcome flows, roles, levels, milestones, and the moments that make a server feel alive.",
    label: "Member journey",
    icon: Users,
    kind: "community",
  },
  {
    eyebrow: "Operations",
    title: "One calm place to run the whole server.",
    body: "Configure tickets, logs, roles, reports, and notifications from a dashboard designed around the way your team actually works.",
    label: "Control center",
    icon: LayoutTemplate,
    kind: "workspace",
  },
];

const STATS = [
  ["12,400+", "communities running better"],
  ["4.2M+", "members supported"],
  ["99.8%", "uptime, always on"],
  ["<120ms", "average response time"],
];

const TESTIMONIALS = [
  ["We stopped juggling five bots and a spreadsheet. Everything feels obvious now.", "Ari D.", "Community Lead"],
  ["The dashboard feels like it was built by someone who has actually run a Discord server.", "Maya R.", "Server Owner"],
  ["Moderation is quieter, onboarding is better, and our staff finally know where to look.", "Noah S.", "Operations"],
];

function ThemeToggle({ darkMode, onToggle }: { darkMode: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      className="mob-icon-button"
      onClick={onToggle}
      aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
      title={darkMode ? "Switch to light mode" : "Switch to dark mode"}
    >
      {darkMode ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function PreviewGallery() {
  return (
    <motion.div
      className="mob-gallery"
      initial={{ opacity: 0, y: 26 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.25, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
    >
      <div className="mob-gallery-track">
        <motion.article className="mob-preview mob-preview-left" whileHover={{ y: -8, rotate: -1 }}>
          <div className="mob-preview-top"><span>Member safety</span><span className="mob-live-dot">Live</span></div>
          <div className="mob-preview-number">47</div>
          <p>spam attempts resolved before staff needed to step in.</p>
          <div className="mob-bars"><i /><i /><i /><i /><i /></div>
        </motion.article>

        <motion.article className="mob-preview mob-preview-main" whileHover={{ y: -10 }}>
          <div className="mob-preview-top"><span>Community overview</span><Command size={14} /></div>
          <div className="mob-mini-grid">
            <div><span className="mob-mini-label">New members</span><b>384</b><em>+18.4%</em></div>
            <div><span className="mob-mini-label">Active today</span><b>2,918</b><em>+7.2%</em></div>
          </div>
          <div className="mob-chart"><span /><span /><span /><span /><span /><span /><span /></div>
          <div className="mob-feed-row"><Bell size={14} /><span>Welcome flow sent to @viola</span><time>now</time></div>
          <div className="mob-feed-row"><ShieldCheck size={14} /><span>Automod updated the safe list</span><time>3m</time></div>
        </motion.article>

        <motion.article className="mob-preview mob-preview-right" whileHover={{ y: -8, rotate: 1 }}>
          <div className="mob-preview-top"><span>Support queue</span><Ticket size={14} /></div>
          <div className="mob-ticket-count">08</div>
          <p>open conversations are assigned, organised, and moving.</p>
          <div className="mob-avatars"><i>A</i><i>J</i><i>M</i><i>+5</i></div>
        </motion.article>
      </div>
    </motion.div>
  );
}

function DiscoveryCard({ item, index }: { item: typeof DISCOVERY_ITEMS[number]; index: number }) {
  const Icon = item.icon;
  return (
    <motion.article
      className={`mob-discovery-card ${item.tint}`}
      initial={{ opacity: 0, y: 18 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.25 }}
      transition={{ delay: index * 0.08, duration: 0.45 }}
      whileHover={{ y: -5 }}
    >
      <div className="mob-discovery-icon"><Icon size={19} /></div>
      <h3>{item.title}</h3>
      <p>{item.description}</p>
      <ChevronRight size={17} className="mob-card-arrow" />
    </motion.article>
  );
}

function FeatureBoard({ board, index }: { board: typeof FEATURE_BOARDS[number]; index: number }) {
  const Icon = board.icon;
  return (
    <section className={`mob-feature-row ${index % 2 ? "reverse" : ""}`}>
      <motion.div
        className="mob-feature-copy"
        initial={{ opacity: 0, x: index % 2 ? 22 : -22 }}
        whileInView={{ opacity: 1, x: 0 }}
        viewport={{ once: true, amount: 0.2 }}
        transition={{ duration: 0.55 }}
      >
        <span className="mob-overline">{board.eyebrow}</span>
        <h2>{board.title}</h2>
        <p>{board.body}</p>
        <a href="#features" className="mob-text-link">Explore {board.eyebrow.toLowerCase()} <ArrowRight size={15} /></a>
      </motion.div>
      <motion.div
        className={`mob-feature-visual ${board.kind}`}
        initial={{ opacity: 0, scale: 0.96 }}
        whileInView={{ opacity: 1, scale: 1 }}
        viewport={{ once: true, amount: 0.2 }}
        transition={{ duration: 0.6, delay: 0.08 }}
      >
        <div className="mob-visual-toolbar"><span>{board.label}</span><Icon size={16} /></div>
        {board.kind === "moderation" && <ModerationVisual />}
        {board.kind === "community" && <CommunityVisual />}
        {board.kind === "workspace" && <WorkspaceVisual />}
      </motion.div>
    </section>
  );
}

function ModerationVisual() {
  return <div className="mob-rule-list">
    {["Block raid patterns", "Limit repeated messages", "Require verified accounts", "Flag suspicious invites"].map((rule, index) => (
      <div key={rule} className="mob-rule"><span className="mob-rule-check"><Check size={13} /></span><span>{rule}</span><i className={index === 2 ? "off" : ""} /></div>
    ))}
  </div>;
}

function CommunityVisual() {
  return <div className="mob-community-visual">
    <div className="mob-community-header"><div className="mob-person"><span>V</span><div><b>Viola joined today</b><small>Welcome flow completed</small></div></div><em>+250 XP</em></div>
    <div className="mob-community-progress"><span>Level 8</span><i><b /></i><span>Level 9</span></div>
    <div className="mob-community-cards"><div><Users size={16} /><b>384</b><small>new this week</small></div><div><Sparkles size={16} /><b>72%</b><small>onboarding done</small></div></div>
  </div>;
}

function WorkspaceVisual() {
  return <div className="mob-workspace-visual">
    <aside><b>Overview</b><span>Security</span><span>Engagement</span><span>Support</span><span>Settings</span></aside>
    <div className="mob-workspace-main"><div className="mob-workspace-title"><div><b>Good afternoon, team.</b><small>Here&apos;s what needs your attention.</small></div><span>Today</span></div><div className="mob-workspace-cards"><i /><i /><i /></div><div className="mob-workspace-line"><span /><span /><span /><span /><span /></div></div>
  </div>;
}

export default function HomePage() {
  const [darkMode, setDarkMode] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [isSigningIn, setIsSigningIn] = useState(false);
  const { status } = useSession();
  const router = useRouter();
  const isAuthenticated = status === "authenticated";

  const openPanel = async () => {
    if (isSigningIn || status === "loading") return;
    if (isAuthenticated) {
      router.push("/dashboard");
      return;
    }

    setIsSigningIn(true);
    try {
      await signIn("discord", { callbackUrl: "/dashboard" });
    } catch {
      setIsSigningIn(false);
    }
  };

  const panelLabel = isSigningIn
    ? "Connecting…"
    : isAuthenticated
      ? "Dashboard"
      : "Log in";

  useEffect(() => {
    setDarkMode(window.localStorage.getItem("midvox-theme") === "dark");
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("theme-dark", darkMode);
    window.localStorage.setItem("midvox-theme", darkMode ? "dark" : "light");
  }, [darkMode]);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="mob-shell">
      <div className="mob-ambient-boxes" aria-hidden="true">
        <i className="mob-ambient-box box-one" />
        <i className="mob-ambient-box box-two" />
        <i className="mob-ambient-box box-three" />
        <i className="mob-ambient-box box-four" />
        <i className="mob-ambient-box box-five" />
      </div>
      <header className={`mob-header ${scrolled ? "scrolled" : ""}`}>
        <nav className="mob-nav">
          <a href="#top" className="mob-brand" aria-label={`${BRAND} home`}><span>m</span>{BRAND.toLowerCase()}</a>
          <div className="mob-nav-links">
            <a href="#discover">Explore</a>
            <a href="#library">Library</a>
            <a href="#stats">Numbers</a>
          </div>
          <div className="mob-nav-actions">
            <ThemeToggle darkMode={darkMode} onToggle={() => setDarkMode((value) => !value)} />
            <button type="button" className="mob-login" onClick={openPanel} disabled={isSigningIn || status === "loading"}>{panelLabel}</button>
            <a href={BOT_INVITE} target="_blank" rel="noopener noreferrer" className="mob-button small">Join for free</a>
          </div>
        </nav>
      </header>

      <main id="top">
        <section className="mob-hero">
          <div className="mob-hero-motion" aria-hidden="true">
            <i className="mob-hero-box hero-box-one" />
            <i className="mob-hero-box hero-box-two" />
            <i className="mob-hero-box hero-box-three" />
          </div>
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }} className="mob-hero-copy">
            <span className="mob-announcement"><Sparkles size={13} /> A calmer way to run Discord</span>
            <h1>The space where great communities <em>come together.</em></h1>
            <p>Security, onboarding, support, and insight—one thoughtful platform for the people building Discord communities that matter.</p>
            <div className="mob-actions">
              <a href={BOT_INVITE} target="_blank" rel="noopener noreferrer" className="mob-button">Add to Discord <ArrowRight size={16} /></a>
              <button type="button" className="mob-secondary-button" onClick={openPanel} disabled={isSigningIn || status === "loading"}>{panelLabel}</button>
            </div>
          </motion.div>
          <PreviewGallery />
        </section>

        <section className="mob-trust-strip" aria-label="Platform benefits">
          <span>Trusted community infrastructure</span><i />
          <span>Set up in minutes</span><i />
          <span>Designed for real teams</span><i />
          <span>Built to grow with you</span>
        </section>

        <section id="stats" className="mob-numbers-section">
          <p className="mob-overline">A growing community library</p>
          <div className="mob-stat-grid">
            {STATS.map(([number, label], index) => <motion.div key={label} initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: index * 0.08 }}><strong>{number}</strong><span>{label}</span></motion.div>)}
          </div>
        </section>

        <section id="discover" className="mob-discover-section">
          <div className="mob-section-intro"><span className="mob-overline">Find the right workflow in seconds</span><h2>Every important moment has a better way to happen.</h2><p>Explore the tools that turn everyday moderation and member management into a smoother experience for everyone.</p></div>
          <div className="mob-search-shell"><Search size={18} /><span>Search the community toolkit</span><kbd>⌘ K</kbd></div>
          <div className="mob-chip-row">{["New member", "Spam protection", "Roles", "Tickets", "Leveling", "Activity", "Logs"].map((chip) => <button key={chip} type="button">{chip}</button>)}</div>
          <div className="mob-discovery-grid">{DISCOVERY_ITEMS.map((item, index) => <DiscoveryCard key={item.title} item={item} index={index} />)}</div>
        </section>

        <section id="library" className="mob-library-section">
          <div className="mob-section-intro center"><span className="mob-overline">From first hello to daily operations</span><h2>A full system for the work behind a thriving server.</h2></div>
          <div className="mob-feature-stack">{FEATURE_BOARDS.map((board, index) => <FeatureBoard key={board.eyebrow} board={board} index={index} />)}</div>
        </section>

        <section className="mob-quotes-section">
          <div className="mob-section-intro"><span className="mob-overline">Made for community people</span><h2>Less admin. More belonging.</h2></div>
          <div className="mob-quote-grid">{TESTIMONIALS.map(([quote, name, role], index) => <motion.figure key={name} initial={{ opacity: 0, y: 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: index * 0.08 }}><blockquote>“{quote}”</blockquote><figcaption><span>{name}</span><small>{role}</small></figcaption></motion.figure>)}</div>
        </section>

        <section className="mob-final-cta">
          <div><span className="mob-overline">Ready when you are</span><h2>Build the community you&apos;d want to join.</h2><p>Start with the essentials. Add the depth when you need it. Keep your team in sync along the way.</p></div>
          <div className="mob-actions"><a href={BOT_INVITE} target="_blank" rel="noopener noreferrer" className="mob-button">Join for free <ArrowRight size={16} /></a><button type="button" className="mob-secondary-button" onClick={openPanel} disabled={isSigningIn || status === "loading"}>{panelLabel}</button></div>
        </section>
      </main>

      <footer className="mob-footer"><a href="#top" className="mob-brand"><span>m</span>{BRAND.toLowerCase()}</a><p>Built for communities that care about the details.</p><div><a href="/docs">Docs</a><a href="/privacy">Privacy</a><a href="/terms">Terms</a></div></footer>
    </div>
  );
}
