"use client";

import { useState, useEffect, useRef } from "react";

export interface DebugEvent {
  time: string;
  type: "HEARTBEAT" | "OTP_CREATED" | "OTP_ROTATED" | "SESSION" | "WARNING" | "ERROR";
  message: string;
  details?: Record<string, unknown>;
}

export interface DebugData {
  sessionId: string | null;
  tier: string;
  maxRes: string;
  deviceFingerprint: string;
  createdAt: number | null;

  // Heartbeat (updated every 30s)
  lastHeartbeat: number | null;
  heartbeatStatus: string;
  riskLevel: string;
  sessionTtl: number;
  totalPlaySeconds: number;
  ipChanges: number;
  currentIp: string;
  seeksLastMinute: number;
  restartsLastHour: number;

  // OTP
  otpRotations: number;
  rotationInterval: number;
  lastRotation: number | null;

  // Behavioral (current interval)
  seeksSinceHeartbeat: number;
  restartsSinceHeartbeat: number;

  // Rate limits (from debug endpoint)
  rateLimits: {
    otp: { used: number; limit: number; window: number };
    login: { used: number; limit: number; window: number };
  } | null;

  // Risk
  riskScore: number;
  riskThreshold: number;
  riskStatus: string;
}

interface DebugPanelProps {
  data: DebugData;
  events: DebugEvent[];
}

type TabId = "session" | "heartbeat" | "otp" | "behavior" | "rates" | "log";

function formatTime(ts: number | null): string {
  if (!ts) return "--";
  return new Date(ts).toLocaleTimeString("en-US", { hour12: false });
}

function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "normal" || status === "alive" || status === "success"
      ? "bg-green-400"
      : status === "warning"
      ? "bg-yellow-400"
      : "bg-red-400";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function ProgressBar({ value, max, label, color = "bg-blue-500" }: {
  value: number;
  max: number;
  label: string;
  color?: string;
}) {
  const pct = Math.min(100, Math.max(0, (value / max) * 100));
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>{label}</span>
        <span>{Math.round(pct)}%</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function CountdownBar({ ttl, max, label }: { ttl: number; max: number; label: string }) {
  const [current, setCurrent] = useState(ttl);

  useEffect(() => {
    setCurrent(ttl);
  }, [ttl]);

  useEffect(() => {
    const interval = setInterval(() => {
      setCurrent((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [ttl]);

  const color = current > max * 0.5 ? "bg-green-500" : current > max * 0.2 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>{label}</span>
        <span className="font-mono">{current}s</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-1000 ${color}`}
          style={{ width: `${Math.min(100, (current / max) * 100)}%` }}
        />
      </div>
    </div>
  );
}

function HeartbeatCountdown({ lastHeartbeat }: { lastHeartbeat: number | null }) {
  const [secondsAgo, setSecondsAgo] = useState(0);

  useEffect(() => {
    const update = () => {
      if (!lastHeartbeat) return;
      setSecondsAgo(Math.floor((Date.now() - lastHeartbeat) / 1000));
    };
    update();
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  }, [lastHeartbeat]);

  const nextIn = Math.max(0, 30 - secondsAgo);

  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>Next heartbeat</span>
        <span className="font-mono">in {nextIn}s</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 bg-cyan-500"
          style={{ width: `${(nextIn / 30) * 100}%` }}
        />
      </div>
    </div>
  );
}

function RotationCountdown({ lastRotation, interval }: { lastRotation: number | null; interval: number }) {
  const [secondsAgo, setSecondsAgo] = useState(0);

  useEffect(() => {
    const update = () => {
      if (!lastRotation) return;
      setSecondsAgo(Math.floor((Date.now() - lastRotation) / 1000));
    };
    update();
    const iv = setInterval(update, 1000);
    return () => clearInterval(iv);
  }, [lastRotation]);

  const nextIn = Math.max(0, interval - secondsAgo);

  return (
    <div>
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>Next rotation</span>
        <span className="font-mono">in {nextIn}s</span>
      </div>
      <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-1000 bg-purple-500"
          style={{ width: `${(nextIn / interval) * 100}%` }}
        />
      </div>
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: string | number; mono?: boolean }) {
  return (
    <div className="flex justify-between py-1 border-b border-gray-800 last:border-0">
      <span className="text-gray-500 text-xs">{label}</span>
      <span className={`text-gray-200 text-xs ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

export default function DebugPanel({ data, events }: DebugPanelProps) {
  const [activeTab, setActiveTab] = useState<TabId>("session");
  const [collapsed, setCollapsed] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const tabs: { id: TabId; label: string; icon: string }[] = [
    { id: "session", label: "Session", icon: "S" },
    { id: "heartbeat", label: "Heartbeat", icon: "H" },
    { id: "otp", label: "OTP", icon: "O" },
    { id: "behavior", label: "Behavior", icon: "B" },
    { id: "rates", label: "Limits", icon: "R" },
    { id: "log", label: "Log", icon: "L" },
  ];

  const eventTypeColor: Record<string, string> = {
    HEARTBEAT: "text-cyan-400",
    OTP_CREATED: "text-green-400",
    OTP_ROTATED: "text-purple-400",
    SESSION: "text-blue-400",
    WARNING: "text-yellow-400",
    ERROR: "text-red-400",
  };

  return (
    <div className="mt-4 bg-gray-950 border border-gray-800 rounded-lg overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-4 py-2.5 bg-gray-900 hover:bg-gray-800 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono bg-yellow-900/60 text-yellow-400 px-1.5 py-0.5 rounded">
            DEBUG
          </span>
          <span className="text-sm text-gray-300 font-medium">Developer Panel</span>
          <StatusDot status={data.riskStatus || "normal"} />
        </div>
        <div className="flex items-center gap-3">
          {!collapsed && (
            <span className="text-xs text-gray-500 font-mono">
              {data.sessionId ? data.sessionId.slice(0, 12) + "..." : "no session"}
            </span>
          )}
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${collapsed ? "" : "rotate-180"}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {!collapsed && (
        <div>
          {/* Tabs */}
          <div className="flex border-b border-gray-800 overflow-x-auto">
            {tabs.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-4 py-2 text-xs font-medium whitespace-nowrap transition-colors ${
                  activeTab === tab.id
                    ? "text-white border-b-2 border-blue-500 bg-gray-900/50"
                    : "text-gray-500 hover:text-gray-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-4 max-h-80 overflow-y-auto" ref={logRef}>
            {activeTab === "session" && (
              <div className="space-y-1">
                <KV label="Session ID" value={data.sessionId || "--"} mono />
                <KV label="Tier" value={`${data.tier} → ${data.maxRes}`} />
                <KV label="Device FP" value={data.deviceFingerprint || "--"} mono />
                <KV label="IP Address" value={data.currentIp || "--"} mono />
                <KV label="Created" value={formatTime(data.createdAt)} mono />
                <KV label="Play Time" value={formatDuration(data.totalPlaySeconds)} />
                <KV label="IP Changes" value={`${data.ipChanges}/3`} />
                <div className="mt-3">
                  <CountdownBar ttl={data.sessionTtl} max={90} label="Session TTL" />
                </div>
              </div>
            )}

            {activeTab === "heartbeat" && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <KV label="Status" value={data.heartbeatStatus || "--"} />
                  <KV
                    label="Risk Level"
                    value={data.riskLevel || "normal"}
                  />
                  <KV label="Last Heartbeat" value={formatTime(data.lastHeartbeat)} mono />
                </div>
                <HeartbeatCountdown lastHeartbeat={data.lastHeartbeat} />
                <div className="mt-2 p-2.5 bg-gray-900 rounded text-xs">
                  <p className="text-gray-500 mb-1">Last payload sent:</p>
                  <p className="text-gray-300 font-mono">
                    seeks: {data.seeksLastMinute} | restarts: {data.restartsLastHour} | play: {formatDuration(data.totalPlaySeconds)}
                  </p>
                </div>
              </div>
            )}

            {activeTab === "otp" && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <KV label="Current OTP" value={`#${data.otpRotations + 1}`} />
                  <KV label="Rotations" value={data.otpRotations} />
                  <KV label="Interval" value={`${data.rotationInterval}s`} />
                  <KV label="Last Rotation" value={formatTime(data.lastRotation)} mono />
                </div>
                <RotationCountdown lastRotation={data.lastRotation || data.createdAt} interval={data.rotationInterval} />
              </div>
            )}

            {activeTab === "behavior" && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <KV label="Seeks (this interval)" value={data.seeksSinceHeartbeat} />
                  <KV label="Restarts (this interval)" value={data.restartsSinceHeartbeat} />
                </div>
                <ProgressBar
                  value={data.seeksLastMinute}
                  max={30}
                  label={`Seeks/min: ${data.seeksLastMinute}/30`}
                  color={data.seeksLastMinute > 20 ? "bg-red-500" : data.seeksLastMinute > 10 ? "bg-yellow-500" : "bg-green-500"}
                />
                <ProgressBar
                  value={data.restartsLastHour}
                  max={15}
                  label={`Restarts/hr: ${data.restartsLastHour}/15`}
                  color={data.restartsLastHour > 10 ? "bg-red-500" : data.restartsLastHour > 5 ? "bg-yellow-500" : "bg-green-500"}
                />
                <ProgressBar
                  value={data.totalPlaySeconds / 3600}
                  max={10}
                  label={`Continuous play: ${formatDuration(data.totalPlaySeconds)}/10h`}
                  color={data.totalPlaySeconds / 3600 > 8 ? "bg-red-500" : "bg-green-500"}
                />
                <div className="mt-2">
                  <div className="flex justify-between text-xs mb-1">
                    <span className="text-gray-500">Risk Score</span>
                    <span className={`font-mono ${
                      data.riskScore >= data.riskThreshold ? "text-red-400" :
                      data.riskScore >= data.riskThreshold * 0.5 ? "text-yellow-400" : "text-green-400"
                    }`}>
                      {data.riskScore}/{data.riskThreshold}
                    </span>
                  </div>
                  <ProgressBar
                    value={data.riskScore}
                    max={data.riskThreshold}
                    label=""
                    color={
                      data.riskScore >= data.riskThreshold ? "bg-red-500" :
                      data.riskScore >= data.riskThreshold * 0.5 ? "bg-yellow-500" : "bg-green-500"
                    }
                  />
                </div>
              </div>
            )}

            {activeTab === "rates" && (
              <div className="space-y-3">
                {data.rateLimits ? (
                  <>
                    <ProgressBar
                      value={data.rateLimits.otp.used}
                      max={data.rateLimits.otp.limit}
                      label={`OTP requests: ${data.rateLimits.otp.used}/${data.rateLimits.otp.limit} (${data.rateLimits.otp.window}s window)`}
                      color={data.rateLimits.otp.used > data.rateLimits.otp.limit * 0.8 ? "bg-red-500" : "bg-green-500"}
                    />
                    <ProgressBar
                      value={data.rateLimits.login.used}
                      max={data.rateLimits.login.limit}
                      label={`Login attempts: ${data.rateLimits.login.used}/${data.rateLimits.login.limit} (${data.rateLimits.login.window}s window)`}
                      color={data.rateLimits.login.used > data.rateLimits.login.limit * 0.8 ? "bg-red-500" : "bg-green-500"}
                    />
                  </>
                ) : (
                  <p className="text-xs text-gray-500">Loading rate limit data...</p>
                )}
              </div>
            )}

            {activeTab === "log" && (
              <div className="space-y-0.5 font-mono text-xs">
                {events.length === 0 ? (
                  <p className="text-gray-500">No events yet...</p>
                ) : (
                  events.map((ev, i) => (
                    <div key={i} className="flex gap-2 py-0.5">
                      <span className="text-gray-600 shrink-0">{ev.time}</span>
                      <span className={`shrink-0 w-24 ${eventTypeColor[ev.type] || "text-gray-400"}`}>
                        {ev.type}
                      </span>
                      <span className="text-gray-300 truncate">{ev.message}</span>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
