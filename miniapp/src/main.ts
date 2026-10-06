import { initTelegram, getInitData } from "./telegram";
import { createSession } from "./api/auth";
import { setSession } from "./state/session";
import { registerRoute, registerNotFound, startRouter } from "./router";
import { mountTabBar } from "./components/tab-bar";
import { ApiError } from "./api/client";
import { uz } from "./locale";

import * as homeScreen from "./screens/home";
import * as catalogScreen from "./screens/catalog";
import * as searchScreen from "./screens/search";
import * as productDetailScreen from "./screens/product-detail";
import * as cartScreen from "./screens/cart";
import * as checkoutScreen from "./screens/checkout";
import * as paymentScreen from "./screens/payment";
import * as receiptUploadScreen from "./screens/receipt-upload";
import * as ordersScreen from "./screens/orders";
import * as orderDetailScreen from "./screens/order-detail";
import * as profileSettingsScreen from "./screens/profile-settings";

import * as adminDashboardScreen from "./screens/admin/dashboard";
import * as adminOrdersScreen from "./screens/admin/orders";
import * as adminOrderDetailScreen from "./screens/admin/order-detail";
import * as adminPaymentsScreen from "./screens/admin/payments";
import * as adminProductsScreen from "./screens/admin/products";
import * as adminProductEditorScreen from "./screens/admin/product-editor";
import * as adminStockScreen from "./screens/admin/stock";

import * as ownerDashboardScreen from "./screens/owner/dashboard";
import * as ownerFinanceScreen from "./screens/owner/finance";
import * as ownerAnalyticsScreen from "./screens/owner/analytics";
import * as ownerAdminsScreen from "./screens/owner/admins";
import * as ownerDiscountsScreen from "./screens/owner/discounts";
import * as ownerAuditScreen from "./screens/owner/audit";
import * as ownerSettingsScreen from "./screens/owner/settings";

function registerRoutes(): void {
  registerRoute("/home", homeScreen.render);
  registerRoute("/catalog", catalogScreen.render);
  registerRoute("/search", searchScreen.render);
  registerRoute("/product/:id", productDetailScreen.render);
  registerRoute("/cart", cartScreen.render);
  registerRoute("/checkout", checkoutScreen.render);
  registerRoute("/payment/:orderId", paymentScreen.render);
  registerRoute("/receipt/:paymentId", receiptUploadScreen.render);
  registerRoute("/orders", ordersScreen.render);
  registerRoute("/order/:id", orderDetailScreen.render);
  registerRoute("/profile", profileSettingsScreen.render);

  // Admin routes — shown in nav only for ADMIN/OWNER (UX only; every
  // admin screen's underlying API calls are independently 403'd by the
  // backend for a USER regardless of whether this nav link is visible,
  // verified by tests/integration/test_admin_permissions_boundary.py, not
  // just assumed from this client-side gate).
  registerRoute("/admin", adminDashboardScreen.render);
  registerRoute("/admin/orders", adminOrdersScreen.render);
  registerRoute("/admin/order/:id", adminOrderDetailScreen.render);
  registerRoute("/admin/payments", adminPaymentsScreen.render);
  registerRoute("/admin/products", adminProductsScreen.render);
  registerRoute("/admin/product/:id", adminProductEditorScreen.render);
  registerRoute("/admin/stock", adminStockScreen.render);

  // Owner routes — shown in nav only for OWNER (state/session.ts::isOwnerRole),
  // not plain ADMIN. Same UX-only-gate discipline as Phase 06: every
  // screen's data calls are independently 403'd server-side otherwise.
  registerRoute("/owner", ownerDashboardScreen.render);
  registerRoute("/owner/finance", ownerFinanceScreen.render);
  registerRoute("/owner/analytics", ownerAnalyticsScreen.render);
  registerRoute("/owner/admins", ownerAdminsScreen.render);
  registerRoute("/owner/discounts", ownerDiscountsScreen.render);
  registerRoute("/owner/audit", ownerAuditScreen.render);
  registerRoute("/owner/settings", ownerSettingsScreen.render);

  registerNotFound((container) => {
    const message = document.createElement("p");
    message.className = "hint";
    message.textContent = "Sahifa topilmadi.";
    container.appendChild(message);
  });
}


async function bootstrap(): Promise<void> {
  initTelegram();
  registerRoutes();

  const app = document.getElementById("app");
  if (!app) return;

  const initData = getInitData();
  if (!initData) {
    // Not running inside Telegram (e.g. local dev in a plain browser) —
    // still mount the router so screens are inspectable/testable, but
    // every authenticated call will correctly fail with 401 until a real
    // Telegram WebView supplies initData.
    mountTabBar();
    startRouter(app);
    return;
  }

  try {
    const session = await createSession(initData);
    setSession(session.token, session.user_id, session.role);
  } catch (error) {
    app.innerHTML = "";
    const message = document.createElement("p");
    message.className = "error-text";
    message.textContent = error instanceof ApiError ? error.message : uz.errorServer;
    app.appendChild(message);
    return;
  }

  mountTabBar();
  startRouter(app);
}

void bootstrap();
