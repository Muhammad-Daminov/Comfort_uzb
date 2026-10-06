import { uploadReceipt } from "../api/payments";
import { errorState } from "../components/error-state";
import { setBackButton, setMainButton, hideMainButton, setMainButtonBusy } from "../telegram";
import { navigate } from "../router";
import { uz } from "../locale";

const MAX_LONG_SIDE = 1600;
const WEBP_QUALITY = 0.85;

/** §14.3: compress in the browser before upload (canvas, max 1600px,
 * WebP q0.85) — a smaller file goes over mobile data. This is a UX/speed
 * optimization only; the backend re-validates/re-processes independently
 * (app/security/uploads.py) and is the actual authority on what's stored. */
async function compressImage(file: File): Promise<File> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_LONG_SIDE / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return file; // no canvas support — fall back to the original file, backend still validates it

  ctx.drawImage(bitmap, 0, 0, width, height);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/webp", WEBP_QUALITY));
  if (!blob) return file;
  return new File([blob], "receipt.webp", { type: "image/webp" });
}

export function render(container: HTMLElement, params: Record<string, string>): void {
  const paymentId = Number(params.paymentId);
  setBackButton(() => navigate(`/payment/${paymentId}`));

  const header = document.createElement("h2");
  header.textContent = "Chekni yuklash";
  container.appendChild(header);

  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "image/*";
  container.appendChild(fileInput);

  const messageSection = document.createElement("div");
  container.appendChild(messageSection);

  hideMainButton();

  fileInput.addEventListener("change", () => {
    const file = fileInput.files?.[0];
    if (!file) {
      hideMainButton();
      return;
    }
    setMainButton(uz.uploadReceipt, () => void handleUpload(file));
  });

  let inFlight = false;

  async function handleUpload(file: File): Promise<void> {
    if (inFlight) return;
    inFlight = true;
    setMainButtonBusy(true);
    messageSection.innerHTML = "";
    try {
      // createImageBitmap rejects formats the WebView cannot decode (HEIC
      // from an iPhone camera, some large JPEGs). That used to surface as a
      // generic "server error" with a retry that could never succeed; the
      // backend (app/security/uploads.py) is the authority on what it
      // accepts, so send the original and let it answer.
      const compressed = await compressImage(file).catch(() => file);
      await uploadReceipt(paymentId, compressed);
      navigate("/home"); // receipt review is admin-side (Phase 06); the user's part is done here
    } catch (error) {
      messageSection.appendChild(errorState(error, () => void handleUpload(file)));
    } finally {
      inFlight = false;
      setMainButtonBusy(false);
    }
  }
}
