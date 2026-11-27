export interface NotificationItem { id: string; event: string; title: string; body: string; link: string | null; created_at: string; read: boolean }
export interface NotificationList { unread: number; items: NotificationItem[]; next_before: string | null }
