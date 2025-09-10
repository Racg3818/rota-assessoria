"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { supabase } from "@/lib/supabaseClient";

export default function DeleteClientButton({
  id,
  name,
}: {
  id: string;
  name?: string;
}) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const onDelete = async () => {
    if (loading) return;
    const ok = confirm(
      `Excluir o cliente${name ? ` "${name}"` : ""}? Essa ação não pode ser desfeita.`
    );
    if (!ok) return;

    setLoading(true);
    const { error } = await supabase.from("clientes").delete().eq("id", id);
    setLoading(false);

    if (error) {
      alert("Erro ao excluir: " + error.message);
    } else {
      router.refresh(); // recarrega a lista
    }
  };

  return (
    <button
      onClick={onDelete}
      disabled={loading}
      className="text-red-600 hover:underline disabled:opacity-50"
    >
      {loading ? "Excluindo..." : "Excluir"}
    </button>
  );
}
