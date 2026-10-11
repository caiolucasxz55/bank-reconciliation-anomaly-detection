import type { Metadata } from "next";

import { ImportCenter } from "@/components/imports/ImportCenter";

export const metadata: Metadata = { title: "Importar dados · Conciliação bancária" };

export default function ImportPage() {
  return <ImportCenter />;
}
