import type { Metadata } from "next";
import { BenchView } from "@/components/BenchView";

export const metadata: Metadata = { title: "Evaluation" };

export default function BenchmarksPage() {
  return <BenchView />;
}
