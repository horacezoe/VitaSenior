import { useRef } from "react";
import { Link } from "react-router-dom";
import { PhoneIncoming, ArrowUpRight } from "lucide-react";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { ErrorNotice } from "./ui";
import { useDisplayed } from "../state/use-displayed";

export function NoticeBanner() {
  const { role } = useSession(),
    { notifications, notificationError, refresh } = useData();
  const element = useRef<HTMLAnchorElement>(null);
  const pending = notifications.filter((n) => n.task_state === "open");
  const notification = pending.length === 1 ? pending[0] : undefined;
  const displayed = useDisplayed(notification, element, refresh);
  if (role !== "elder") return null;
  if (!pending.length)
    return <ErrorNotice error={notificationError} retry={refresh} />;
  return (
    <Link
      ref={element}
      className="notice-banner"
      to={
        notification
          ? `/notifications/${notification.notification_id}`
          : "/notifications"
      }
    >
      <span className="notice-phone">
        <PhoneIncoming size={22} />
      </span>
      <span>
        <strong>今日记录核对</strong>
        <small>
          {pending.length > 1
            ? `有${pending.length}条待核对内容，查看全部`
            : displayed.error
              ? "状态同步稍慢，仍可打开查看"
              : notification?.audio_asset_id
                ? "有一份关心，等您接听"
                : "有一条提醒，点开查看完整内容"}
        </small>
      </span>
      <ArrowUpRight size={19} />
    </Link>
  );
}
