import type { Metadata } from "next";
import { MissionPage } from "@/components/MissionPage";

export const metadata: Metadata = { title: "Mission" };

export default function Page({ params }: { params: { id: string } }) {
  return <MissionPage id={decodeURIComponent(params.id)} />;
}
