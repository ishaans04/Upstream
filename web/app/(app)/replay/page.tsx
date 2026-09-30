import type { Metadata } from "next";
import { ReplayView } from "@/components/ReplayView";

export const metadata: Metadata = { title: "Belief replay" };

export default function ReplayPage() {
  return <ReplayView />;
}
