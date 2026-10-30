-- Contabilidad de la subasta y del crafteo: qué compras y a cuánto, qué fabricas, qué
-- pones a la venta (y el depósito), qué se vende (lo dice el correo de la subasta) y
-- cuánto tiempo pasas gestionándolo. El motor calcula con esto el beneficio real.
local ADDON, ns = ...

local MAX_EVENTS = 5000
local MAX_WINDOW_SECONDS = 30 * 60   -- una ventana abierta más rato seguramente es estar ausente
local DUPLICATE_SECONDS = 10

local seq = 0

local function Record(kind, data)
  seq = seq + 1
  data.type = kind
  data.t = data.t or time()
  data.char = ns.charKey
  data.key = table.concat({ data.t, ns.charKey or "?", kind, seq }, "|")
  local ledger = PitiGoldsDB.ledger
  ledger[#ledger + 1] = data
end
ns.RecordLedger = Record

local function Hook(owner, name, fn)
  if owner and type(owner[name]) == "function" then
    hooksecurefunc(owner, name, function(...)
      local ok, err = pcall(fn, ...)
      if not ok then ns.ReportError("contabilidad " .. name, err) end
    end)
  end
end

-- Compras de materiales (commodities): llegan directas a las bolsas ----------------------

local quote, pendingBuy

ns.On("COMMODITY_PRICE_UPDATED", function(_, unitPrice, totalPrice)
  quote = { unit = unitPrice, total = totalPrice }
end)

Hook(C_AuctionHouse, "ConfirmCommoditiesPurchase", function(itemID, quantity)
  pendingBuy = { itemID = itemID, qty = quantity, money = GetMoney(), total = quote and quote.total }
end)

ns.On("COMMODITY_PURCHASE_SUCCEEDED", function()
  local p = pendingBuy
  pendingBuy = nil
  if not p then return end
  -- Lo exacto es el precio total confirmado; si no llegó, lo que bajó el oro.
  local spent = p.total or (p.money - GetMoney())
  Record("buy", { itemID = p.itemID, qty = p.qty, money = spent })
  ns.NoteItem(p.itemID, ns.ItemNameByID(p.itemID))
end)
ns.On("COMMODITY_PURCHASE_FAILED", function() pendingBuy = nil end)

-- Lo que pones a la venta -----------------------------------------------------------------

local function ItemIDAt(location)
  if C_Item and C_Item.GetItemID then
    local ok, id = pcall(C_Item.GetItemID, location)
    if ok then return id end
  end
end

Hook(C_AuctionHouse, "PostCommodity", function(location, duration, quantity, unitPrice)
  local itemID = ItemIDAt(location)
  local ok, deposit = pcall(C_AuctionHouse.CalculateCommodityDeposit, itemID, duration, quantity)
  Record("post", { itemID = itemID, qty = quantity, unit = unitPrice, deposit = ok and deposit or nil })
end)

Hook(C_AuctionHouse, "PostItem", function(location, duration, quantity, bid, buyout)
  local itemID = ItemIDAt(location)
  local ok, deposit = pcall(C_AuctionHouse.CalculateItemDeposit, location, duration, quantity)
  Record("post", { itemID = itemID, qty = quantity, unit = buyout or bid, deposit = ok and deposit or nil })
end)

-- Ventas y compras de objetos: llegan por correo con su factura ---------------------------
-- Se apuntan al recoger el dinero o el objeto, que solo se puede hacer una vez por correo.

local recent = {}  -- firma de la factura -> hora, para no contar dos veces el mismo correo

local function TakeFromMail(index)
  if not GetInboxInvoiceInfo then return end
  local invoiceType, itemName, _, bid, _, deposit, consignment, _, _, count = GetInboxInvoiceInfo(index)
  if invoiceType ~= "seller" and invoiceType ~= "buyer" then return end
  local signature = table.concat({ invoiceType, itemName or "?", count or 1, bid or 0, deposit or 0 }, "|")
  local now = time()
  if recent[signature] and now - recent[signature] < DUPLICATE_SECONDS then return end
  recent[signature] = now
  if invoiceType == "seller" then
    Record("sale", { itemName = itemName, qty = count or 1, money = bid, cut = consignment, deposit = deposit })
  else
    Record("buy", { itemName = itemName, qty = count or 1, money = bid })
  end
end

Hook(_G, "TakeInboxMoney", TakeFromMail)
Hook(_G, "AutoLootMailItem", TakeFromMail)
Hook(_G, "TakeInboxItem", TakeFromMail)

-- Crafteos ------------------------------------------------------------------------------------

ns.On("UNIT_SPELLCAST_SUCCEEDED", function(_, unit, _, spellID)
  if unit ~= "player" or (InCombatLockdown and InCombatLockdown()) then return end
  local recipe = PitiGoldsDB.recipes[spellID]
  if recipe then
    Record("craft", { recipeID = spellID, itemID = recipe.output, qty = recipe.qtyMin or 1 })
  end
end)

-- Tiempo de gestión -----------------------------------------------------------------------------

local openSince = {}

local function Opened(kind)
  openSince[kind] = openSince[kind] or time()
end

local function Closed(kind)
  local start = openSince[kind]
  openSince[kind] = nil
  if start and time() > start then
    Record("time", { t = start, kind = kind, seconds = math.min(time() - start, MAX_WINDOW_SECONDS) })
  end
end

local WINDOWS = {
  { "AUCTION_HOUSE_SHOW", "AUCTION_HOUSE_CLOSED", "subasta" },
  { "TRADE_SKILL_SHOW", "TRADE_SKILL_CLOSE", "profesion" },
  { "MAIL_SHOW", "MAIL_CLOSED", "correo" },
}
for _, w in ipairs(WINDOWS) do
  local kind = w[3]
  if ns.On(w[2], function() Closed(kind) end) then
    ns.On(w[1], function() Opened(kind) end)
  end
end

ns.On("PLAYER_LOGOUT", function()
  for kind in pairs(openSince) do Closed(kind) end
end)

-- Limpieza: fuera lo que el motor ya tiene y, si aun así hay demasiado, lo más viejo.
ns.On("PLAYER_LOGIN", function()
  local gen = PitiGoldsGenerated
  local upTo = (type(gen) == "table" and tonumber(gen.ledgerIngestedUpTo)) or 0
  local kept = {}
  for _, e in ipairs(PitiGoldsDB.ledger) do
    if (e.t or 0) > upTo then kept[#kept + 1] = e end
  end
  while #kept > MAX_EVENTS do table.remove(kept, 1) end
  PitiGoldsDB.ledger = kept
end)
