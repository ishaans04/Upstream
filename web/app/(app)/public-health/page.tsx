import type { Metadata } from "next";
import { HealthView } from "@/components/HealthView";

export const metadata: Metadata = { title: "Public health" };

export default function PublicHealthPage() {
  return <HealthView />;
}
