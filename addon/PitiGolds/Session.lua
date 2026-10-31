-- Sesión de farmeo en vivo: lo que llevas ganado con este personaje desde que empezaste a
-- jugar (o desde que pulsaste Reiniciar), con la lista de objetos y lo que vale cada uno.
-- Cuenta lo mismo que el registro de farmeos (nada del correo, la subasta, el banco...)
-- y se actualiza en cuanto entra algo en las bolsas.
--
-- Cada objeto se valora con el precio más reciente que haya: un escaneo de la subasta que
-- el motor aún no ha leído, el precio del motor o, si paga más, el vendedor.
local ADDON, ns = ...

local AH_CUT = 0.05
local MARKET_SHARE = 0.15            -- como el motor: media del 15 % más barato a la venta
local NEW_SESSION_AFTER = 30 * 60    -- tanto rato sin jugar con el personaje empieza otra sesión
local MIN_SECONDS = 300              -- el oro por hora no se calcula sobre menos de 5 minutos
local WIDTH, HEIGHT = 380, 340
local ROWS, ROW_HEIGHT = 14, 16
local COLUMNS = { { "Objeto", 180 }, { "Precio", 92 }, { "Total", 84 } }

local S = {}
ns.Session = S

-- Precios ---------------------------------------------------------------------------------

-- Lo último escaneado de cada objeto que el motor aún no ha leído; se rehace al escanear.
-- El precio se saca solo de los objetos que hacen falta: un escaneo completo trae miles.
local scanText, scanCache

-- "min,cantidad[,subastas,vendedores]|precio:cantidad;..." -> precio de mercado
local function MarketFromScan(text)
  local head, book = text:match("^([^|]*)|?(.*)$")
  local min, qty = (head or ""):match("^(%d+),(%d+)")
  min, qty = tonumber(min), tonumber(qty)
  if not min then return nil end
  if book == "" or qty <= 0 then return min end
  local target = math.max(1, math.ceil(qty * MARKET_SHARE))
  local taken, cost = 0, 0
  for price, n in book:gmatch("(%d+):(%d+)") do
    local take = math.min(tonumber(n), target - taken)
    cost = cost + take * tonumber(price)
    taken = taken + take
    if taken >= target then break end
  end
  if taken == 0 then return min end
  return math.floor(cost / taken + 0.5)
end

local function BuildScanIndex()
  scanText, scanCache = {}, {}
  local seen = {}
  for _, scan in ipairs(PitiGoldsDB.scans or {}) do
    local t = scan.time or 0
    for itemID, text in pairs(scan.items or {}) do
      if type(text) == "string" and t >= (seen[itemID] or -1) then
        scanText[itemID], seen[itemID] = text, t
      end
    end
  end
end

local function ScanPrice(itemID)
  if not scanText then BuildScanIndex() end
  local price = scanCache[itemID]
  if price == nil then
    local text = scanText[itemID]
    price = text and MarketFromScan(text) or false
    scanCache[itemID] = price
  end
  return price or nil
end

local addScan = ns.AddScan
function ns.AddScan(scan)
  addScan(scan)
  scanText, scanCache = nil, nil
end

-- Lo que vale una unidad y de dónde sale el precio: "escaneo" (de la subasta, aún sin leer
-- por el motor), "subasta" (el del motor) o "vendedor". 0 y nil si no hay ninguno.
function ns.ItemValue(itemID)
  local market, source = ScanPrice(itemID), "escaneo"
  if not market then
    local gen = PitiGoldsGenerated
    local text = type(gen) == "table" and gen.prices and gen.prices[itemID]
    market, source = text and tonumber(text:match("^(%d+)")), "subasta"
  end
  local entry = PitiGoldsDB.items and PitiGoldsDB.items[itemID]
  local vendor = type(entry) == "table" and entry.sell or nil
  if vendor == nil then vendor = ns.ItemSellPrice(itemID) end
  local net = market and math.floor(market * (1 - AH_CUT)) or nil
  if net and net > (vendor or 0) then return net, source end
  if vendor and vendor > 0 then return vendor, "vendedor" end
  return 0, nil
end

-- Sesión ------------------------------------------------------------------------------------

local function Current()
  local c = ns.Char()
  return c and c.session
end

function S.Reset()
  local c = ns.Char()
  if not c then return end
  local now = time()
  c.session = { start = now, seen = now, away = 0, money = 0, items = {} }
  if ns.RefreshUI then ns.RefreshUI() end
end

function S.AddItem(itemID, count)
  local s = Current()
  if not s then return end
  s.items[itemID] = (s.items[itemID] or 0) + count
  s.seen = time()
end

function S.AddMoney(copper)
  local s = Current()
  if not s then return end
  s.money = s.money + copper
  s.seen = time()
end

-- Al entrar: sigue la sesión si hace poco que jugaste con este personaje (un /reload, un
-- cambio rápido de personaje) sin contar el rato fuera; si no, empieza otra.
function S.OnLogin()
  local s = Current()
  local now = time()
  if not s or now - (s.seen or s.start or 0) > NEW_SESSION_AFTER then
    S.Reset()
  else
    s.away = (s.away or 0) + math.max(0, now - (s.seen or now))
    s.seen = now
  end
end

local function ItemName(itemID)
  local entry = PitiGoldsDB.items and PitiGoldsDB.items[itemID]
  return (type(entry) == "table" and entry.name) or ns.ItemNameByID(itemID) or ("objeto " .. itemID)
end

-- Lo ganado en la sesión: tiempo jugado, oro suelto, objetos valorados y oro por hora.
function S.Summary()
  local s = Current()
  if not s then return nil end
  local elapsed = math.max(0, time() - s.start - (s.away or 0))
  local items, value = {}, 0
  for itemID, count in pairs(s.items) do
    local unit, source = ns.ItemValue(itemID)
    value = value + unit * count
    items[#items + 1] = { id = itemID, name = ItemName(itemID), count = count, unit = unit,
                          total = unit * count, source = source }
  end
  table.sort(items, function(a, b)
    if a.total ~= b.total then return a.total > b.total end
    return a.name < b.name
  end)
  local total = s.money + value
  return { elapsed = elapsed, money = s.money, value = value, total = total, items = items,
           perHour = math.floor(total * 3600 / math.max(elapsed, MIN_SECONDS)) }
end

function S.Duration(seconds)
  local minutes = math.floor(seconds / 60)
  if minutes < 60 then return ("%d min"):format(minutes) end
  return ("%d h %02d min"):format(math.floor(minutes / 60), minutes % 60)
end

ns.On("PLAYER_LOGIN", S.OnLogin)
ns.On("PLAYER_LOGOUT", function()
  local s = Current()
  if s then s.seen = time() end
end)

-- Ventana -----------------------------------------------------------------------------------

local window, summaryText, legendText
local rowFrames = {}
local offset = 0

local function PriceText(item)
  if not item.source then return "|cff999999sin precio|r" end
  local text = ns.Money(item.unit)
  if item.source == "vendedor" then return text .. " |cff999999(v)|r" end
  return text
end

function S.Refresh()
  if not window or not window:IsShown() then return end
  local s = S.Summary()
  if not s then return end
  local head = { ("Llevas %s: |cffffd100%s|r (%s por hora)"):format(
    S.Duration(s.elapsed), ns.Money(s.total), ns.Money(math.floor(s.perHour / 100) * 100)) }
  head[#head + 1] = ("Oro suelto: %s · objetos: %s"):format(ns.Money(s.money), ns.Money(s.value))
  if PitiGoldsDB.farmLabel then head[#head + 1] = "Farmeo: " .. PitiGoldsDB.farmLabel end
  summaryText:SetText(table.concat(head, "\n"))

  offset = math.max(0, math.min(offset, #s.items - ROWS))
  for i, frame in ipairs(rowFrames) do
    local item = s.items[i + offset]
    if item then
      frame.cells[1]:SetText(("%s ×%d"):format(item.name, item.count))
      frame.cells[2]:SetText(PriceText(item))
      frame.cells[3]:SetText(ns.Money(item.total))
      frame:Show()
    else
      frame:Hide()
    end
  end
  if #s.items == 0 then
    rowFrames[1].cells[1]:SetText("|cff999999Aún no has farmeado nada en esta sesión.|r")
    rowFrames[1].cells[2]:SetText("")
    rowFrames[1].cells[3]:SetText("")
    rowFrames[1]:Show()
  end
end

-- Para las pruebas: el texto de cada fila visible.
function S.RowTexts()
  local out = {}
  for _, frame in ipairs(rowFrames) do
    if frame:IsShown() then
      out[#out + 1] = table.concat({ frame.cells[1]:GetText() or "", frame.cells[2]:GetText() or "",
                                     frame.cells[3]:GetText() or "" }, " | ")
    end
  end
  return table.concat(out, "\n")
end

function S.SummaryText()
  return summaryText and summaryText:GetText() or ""
end

local function Scroll(delta)
  offset = offset - delta
  S.Refresh()
end

local function CreateWindow()
  window = CreateFrame("Frame", "PitiGoldsSession", UIParent, "BackdropTemplate")
  window:SetSize(WIDTH, HEIGHT)
  window:SetPoint("CENTER", 260, 0)
  window:SetFrameStrata("DIALOG")
  window:SetMovable(true)
  window:SetClampedToScreen(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  window:SetBackdrop({
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    edgeSize = 14,
    insets = { left = 4, right = 4, top = 4, bottom = 4 },
  })
  window:SetBackdropColor(0, 0, 0, 0.92)
  if UISpecialFrames then table.insert(UISpecialFrames, "PitiGoldsSession") end

  local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", 12, -10)
  title:SetText("PitiGolds: sesión")
  local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", -2, -2)
  close:SetScript("OnClick", function() window:Hide() end)

  summaryText = window:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  summaryText:SetPoint("TOPLEFT", 12, -30)
  summaryText:SetWidth(WIDTH - 24)
  summaryText:SetJustifyH("LEFT")

  local list = CreateFrame("Frame", nil, window)
  list:SetPoint("TOPLEFT", 12, -82)
  list:SetSize(WIDTH - 24, ROW_HEIGHT * (ROWS + 1))
  list:EnableMouseWheel(true)
  list:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)

  local x = 0
  for _, col in ipairs(COLUMNS) do
    local header = list:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    header:SetPoint("TOPLEFT", x + 4, -2)
    header:SetText(col[1])
    x = x + col[2]
  end

  for i = 1, ROWS do
    local row = CreateFrame("Frame", nil, list)
    row:SetSize(WIDTH - 24, ROW_HEIGHT)
    row:SetPoint("TOPLEFT", 0, -ROW_HEIGHT * i)
    row:EnableMouseWheel(true)
    row:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)
    row.cells = {}
    x = 0
    for c, col in ipairs(COLUMNS) do
      local cell = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      cell:SetPoint("LEFT", row, "LEFT", x + 4, 0)
      cell:SetWidth(col[2] - 8)
      cell:SetJustifyH(c == 1 and "LEFT" or "RIGHT")
      if cell.SetWordWrap then cell:SetWordWrap(false) end
      row.cells[c] = cell
      x = x + col[2]
    end
    rowFrames[i] = row
  end

  legendText = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  legendText:SetPoint("BOTTOMLEFT", 12, 38)
  legendText:SetWidth(WIDTH - 24)
  legendText:SetJustifyH("LEFT")
  legendText:SetText("Precio de la subasta sin la comisión (el último escaneo, si el motor aún no lo ha"
    .. " leído) o del vendedor si paga más (v).")

  local reset = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  reset:SetSize(110, 22)
  reset:SetPoint("BOTTOMLEFT", 12, 10)
  reset:SetText("Reiniciar")
  reset:SetScript("OnClick", function()
    S.Reset()
    ns.Print("sesión nueva: empieza a contar desde ahora.")
  end)
end

function S.Open()
  if not window then CreateWindow() end
  offset = 0
  window:Show()
  S.Refresh()
end

function S.Toggle()
  if window and window:IsShown() then
    window:Hide()
  else
    S.Open()
  end
end

ns.Command("sesion", "lo que llevas ganado en esta sesión (/pg sesion reiniciar para empezar otra)", function(text)
  if ns.Trim(text or ""):lower() == "reiniciar" then
    S.Reset()
    ns.Print("sesión nueva: empieza a contar desde ahora.")
  else
    S.Toggle()
  end
end)
