import { useEffect, useState } from "react";
import { api } from "./api";

declare const __APP_VERSION__: string;

export function VersionLabel() {
  const [version, setVersion] = useState(__APP_VERSION__);
  useEffect(() => {
    const controller = new AbortController();
    api<{ version: string }>("/api/health", undefined, undefined, {
      background: true, signal: controller.signal,
    }).then((health) => {
      if (typeof health.version === "string") setVersion(health.version);
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  return <span title={`后台：${version}；界面：${__APP_VERSION__}`}>v{version}</span>;
}
