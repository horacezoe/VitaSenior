import { useRef } from "react";
import { Link } from "react-router-dom";
import { PhoneIncoming, ArrowUpRight } from "lucide-react";
import { useSession } from "../state/session";
import { useData } from "../state/data";
import { ErrorNotice } from "./ui";
import { reminderTitle } from "./records";
import { useDisplayed } from "../state/use-displayed";

export function NoticeBanner() {
  const { role } = useSession(),
    { notifications, notificationError, refresh } = useData();
  const element = useRef<HTMLAnchorElement>(null);
  const notification = notifications[0];
  const displayed = useDisplayed(notification, element, refresh);
  if (role !== "elder") return null;
  if (!notification)
    return <ErrorNotice error={notificationError} retry={refresh} />;
  return (
    <Link
      ref={element}
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
          {displayed.error
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
