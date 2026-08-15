"use client";

import { useMemo, useState } from "react";
import { Button, Modal, StatusBadge } from "@ads-os/ui";
import { useCurrentUser } from "./AuthGate";
import { createApiClient } from "@/lib/api";

const ROLE_LABEL: Record<string, string> = {
  owner: "Владелец",
  specialist: "Специалист",
  viewer: "Просмотр",
};

/** Первые буквы имени и фамилии — для кружка в верхней панели. */
function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() ?? "").join("") || "?";
}

export function UserMenu() {
  const api = useMemo(() => createApiClient(), []);
  const user = useCurrentUser();
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);

  const signOut = async () => {
    setLeaving(true);
    try {
      await api.logout();
    } finally {
      // Именно перезагрузка, а не переход роутером: после выхода не должно
      // остаться ни строчки состояния от прошлого пользователя. Роутер
      // сохранил бы кэш страниц и данные в памяти.
      window.location.reload();
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Профиль: ${user.full_name}`}
        className="rounded-pill hover:bg-surface-hover focus-visible:outline-focus flex items-center gap-2 py-1 pr-2 pl-1 transition-colors duration-(--duration-fast) ease-out focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        <span
          aria-hidden="true"
          className="bg-bg-secondary text-text-secondary text-micro flex size-7 items-center justify-center rounded-full font-medium"
        >
          {initials(user.full_name)}
        </span>
        <span className="text-caption text-text-primary hidden lg:inline">{user.full_name}</span>
      </button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={user.full_name}
        description={user.organization_name}
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Закрыть
            </Button>
            <Button onClick={() => void signOut()} loading={leaving}>
              Выйти
            </Button>
          </>
        }
      >
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-body-sm text-text-secondary">Почта</span>
            <span className="text-body-sm text-text-primary break-all">{user.email}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-body-sm text-text-secondary">Роль</span>
            <StatusBadge tone="neutral">{ROLE_LABEL[user.role] ?? user.role}</StatusBadge>
          </div>
          <p className="text-caption text-text-secondary">
            Вход выполнен через Яндекс ID. Пароля у этой учётной записи нет — менять и
            восстанавливать нечего.
          </p>
        </div>
      </Modal>
    </>
  );
}
