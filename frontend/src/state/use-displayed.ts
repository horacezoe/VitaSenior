import { useEffect, useRef, useState, type RefObject } from "react";
import { uid, type Notification, type Schemas } from "../api/client";
import { actuallyVisible } from "../media/visibility";
import { useSession } from "./session";

export function useDisplayed<T extends HTMLElement>(
  notification: Notification | null | undefined,
  element: RefObject<T | null>,
  shown?: (value: Notification) => void,
) {
  const { api, role } = useSession(),
    callback = useRef(shown),
    retry = useRef<() => void>(() => {});
  const [error, setError] = useState<unknown>(null);
  callback.current = shown;
  useEffect(() => {
    setError(null);
    const target = element.current;
    if (
      !notification ||
      notification.displayed_at ||
      role !== "elder" ||
      !target
    ) {
      retry.current = () => {};
      return;
    }
    let active = true,
      sent = false,
      frame = 0,
      nextRetryAt = 0;
    const controller = new AbortController();
    const mark = () => {
      if (
        !active ||
        sent ||
        Date.now() < nextRetryAt ||
        !target.isConnected ||
        !actuallyVisible(
          target.getBoundingClientRect(),
          { width: window.innerWidth, height: window.innerHeight },
          document.visibilityState,
        )
      )
        return;
      const style = getComputedStyle(target);
      if (
        style.visibility === "hidden" ||
        style.display === "none" ||
        style.opacity === "0"
      )
        return;
      sent = true;
      const storageKey = `vitasenior.display-event.${notification.notification_id}`;
      const eventId = sessionStorage.getItem(storageKey) || uid("display");
      sessionStorage.setItem(storageKey, eventId);
      void api
        .post<Schemas["EventResult"]>(
          `/api/v1/notifications/${notification.notification_id}/events`,
          { event_id: eventId, event_type: "displayed" },
          eventId,
          controller.signal,
        )
        .then((result) => {
          if (active) {
            setError(null);
            callback.current?.(result.notification);
          }
        })
        .catch((reason) => {
          if (active && !controller.signal.aborted) {
            sent = false;
            nextRetryAt = Date.now() + 5000;
            setError(reason);
          }
        });
    };
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(mark);
    };
    const observer =
      typeof IntersectionObserver !== "undefined"
        ? new IntersectionObserver(schedule, {
            threshold: [0, 0.01, 0.25, 0.5, 1],
          })
        : null;
    observer?.observe(target);
    retry.current = () => {
      nextRetryAt = 0;
      schedule();
    };
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => {
      active = false;
      controller.abort();
      cancelAnimationFrame(frame);
      observer?.disconnect();
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", schedule);
      retry.current = () => {};
    };
  }, [
    api,
    role,
    notification?.notification_id,
    notification?.displayed_at,
    element,
  ]);
  return { error, retry: () => retry.current() };
}
