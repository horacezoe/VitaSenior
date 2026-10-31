import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PhoneIncoming, ArrowUpRight } from "lucide-react";
import { uid } from "../api/client";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { ErrorNotice } from "./ui";
import { reminderTitle } from "./records";

export function NoticeBanner() {
  const { api, role } = useSession(),
    { notifications, notificationError, refresh } = useData(),
    [failed, setFailed] = useState(false);
  const notification = notifications[0];
  useEffect(() => {
    if (!notification || role !== "elder" || notification.displayed_at) return;
    const id = requestAnimationFrame(() => {
      if (document.visibilityState !== "visible") return;
      const storageKey = `vitasenior.display-event.${notification.notification_id}`;
      const eventId = sessionStorage.getItem(storageKey) || uid("display");
      sessionStorage.setItem(storageKey, eventId);
      void api
        .post(
          `/api/v1/notifications/${notification.notification_id}/events`,
          { event_id: eventId, event_type: "displayed" },
          eventId,
        )
        .catch(() => setFailed(true));
    });
    return () => cancelAnimationFrame(id);
  }, [api, notification?.notification_id, notification?.displayed_at, role]);
  if (role !== "elder") return null;
  if (!notification)
    return <ErrorNotice error={notificationError} retry={refresh} />;
  return (
    <Link
      className="notice-banner"
      to={`/notifications/${notification.notification_id}`}
    >
      <span className="notice-phone">
        <PhoneIncoming size={22} />
      </span>
      <span>
        <strong>
          {notification.proposal_id
            ? "家人有一项修改想和您确认"
            : reminderTitle(notification.title)}
        </strong>
        <small>
          {failed
            ? "状态同步稍慢，仍可打开查看"
            : notification.audio_asset_id
              ? "有一份关心，等您接听"
              : "有一条提醒，点开查看完整内容"}
        </small>
      </span>
      <ArrowUpRight size={19} />
    </Link>
  );
}
