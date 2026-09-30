import type { Metadata } from "next";
import { Suspense } from "react";
import { ConsoleLoader } from "@/components/ConsoleLoader";
import { Loading } from "@/components/States";

export const metadata: Metadata = { title: "Console" };

export default function ConsolePage() {
  return <Suspense fallback={<Loading what="the console" />}><ConsoleLoader /></Suspense>;
}
