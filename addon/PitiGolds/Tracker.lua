-- Farmeos activos: los métodos que eliges en la ventana de métodos («Farmear este» o
-- «Craftear este») para hacerlos ahora. Cada uno va en su recuadro de una ventana pequeña,
-- pensada para tenerla abierta mientras juegas (se arrastra, cambia de tamaño y se cierra):
--   - farmeos: cuántos llevas de sus objetos, lo que valen y el oro por hora;
--   - crafteos: los materiales que tienes de los que hacen falta (5/8).
-- Al pulsar el nombre se despliega el resto. Cada uno tiene su temporizador, que se pone en
-- marcha solo con el primer botín del farmeo (o con Empezar): solo cuenta lo que entra
-- mientras corre. Lo farmeado con farmeos en marcha queda apuntado con su id en el registro
-- de farmeos, así el motor mide tu oro por hora real de cada método.
local ADDON, ns = ...

local T = {}
ns.Tracker = T

local DEFAULT_WIDTH, DEFAULT_HEIGHT = 230, 240
local MIN_WIDTH, MIN_HEIGHT = 190, 80
local MAX_WIDTH, MAX_HEIGHT = 600, 900
local MAX_ACTIVE = 8
local MIN_SECONDS = 300          -- el oro por hora no se calcula sobre menos de 5 minutos
local RESUME_WITHIN = 30 * 60    -- tras un /reload o un cambio rápido de personaje sigue en marcha
local LOOT_WINDOW = 2            -- segundos entre las monedas de un bicho y sus objetos
local SHOWN_ITEMS = 4            -- objetos en el recuadro plegado
local LINE = 12
local PAD = 6
local BOX_GAP = 4
local HEADER_HEIGHT = 14
local BUTTON_HEIGHT = 18

-- Datos ------------------------------------------------------------------------------------

function T.List()
  local c = ns.Char()
  if not c then return {} end
  c.activeFarms = c.activeFarms or {}
  return c.activeFarms
end

local function Find(key)
  for i, f in ipairs(T.List()) do
    if f.key == key then return f, i end
  end
end
T.Find = Find

-- El id de una fila de la ventana de métodos: el del farmeo o «receta:<número>».
function T.KeyFor(row)
  if row.recipe then return "receta:" .. row.recipe end
  return row.key
end

function T.IsActive(key)
  return Find(key) ~= nil
end

-- La fila del motor (PitiGoldsGenerated.methods) de un farmeo activo; nil si ya no está.
function T.Data(f)
  local gen = PitiGoldsGenerated
  local methods = type(gen) == "table" and type(gen.methods) == "table" and gen.methods or nil
  if not methods then return nil end
  for _, row in ipairs(methods[f.kind == "craft" and "crafts" or "farms"] or {}) do
    if T.KeyFor(row) == f.key then return row end
  end
end

function T.Elapsed(f)
  return (f.elapsed or 0) + (f.started and math.max(0, time() - f.started) or 0)
end

-- El nombre con el que se apunta lo farmeado: los farmeos en marcha (nil si no hay ninguno).
function T.Label()
  local keys = {}
  for _, f in ipairs(T.List()) do
    if f.kind == "farm" and f.started then keys[#keys + 1] = f.key end
  end
  if #keys == 0 then return nil end
  return table.concat(keys, "+")
end

-- Si el objeto es de los que da el farmeo según el catálogo.
function T.IsFarmItem(data, itemID)
  for _, id in ipairs(data and data.items or {}) do
    if id == itemID then return true end
  end
  return false
end

-- Lo que cuenta para un farmeo. Si da monedas es de matar bichos: todo lo que sueltan (grises,
-- verdes, tela que no es la del catálogo...), igual que la sesión y que el motor al medirlo. Si no,
-- es de recolectar: solo sus objetos, para no sumarle lo que recoges de paso. Si no dice qué
-- objetos da (o es uno que has medido tú), todo.
local function Counts(data, itemID)
  if not data or not data.items or #data.items == 0 or data.coins then return true end
  return T.IsFarmItem(data, itemID)
end

local function CountsMoney(data)
  return not data or data.coins or not data.items or #data.items == 0
end

-- Monedas que llegan antes que el primer objeto del farmeo (el oro se avisa antes que las
-- bolsas): si el objeto llega enseguida, son del mismo bicho y cuentan.
local pendingMoney = {}

-- Lo que entra en las bolsas (Farming.lua ya ha descartado correo, subasta, banco...).
function T.AddItem(itemID, count)
  local changed = false
  for _, f in ipairs(T.List()) do
    if f.kind == "farm" and Counts(T.Data(f), itemID) then
      -- El primer botín pone en marcha el temporizador de un farmeo que aún no ha empezado.
      if not f.started and (f.elapsed or 0) == 0 then
        f.started = time()
        local pending = pendingMoney[f.key]
        if pending and f.started - pending.at <= LOOT_WINDOW then f.money = (f.money or 0) + pending.copper end
      end
      pendingMoney[f.key] = nil
      if f.started then
        f.items[itemID] = (f.items[itemID] or 0) + count
        changed = true
      end
    end
  end
  return changed
end

function T.AddMoney(copper)
  local changed = false
  for _, f in ipairs(T.List()) do
    if f.kind == "farm" and CountsMoney(T.Data(f)) then
      if f.started then
        f.money = (f.money or 0) + copper
        changed = true
      elseif (f.elapsed or 0) == 0 then
        pendingMoney[f.key] = { copper = copper, at = time() }
      end
    end
  end
  return changed
end

local function Silver(copper)
  return ns.Money(math.floor(copper / 100) * 100)
end

function T.FarmSummary(f, data)
  local list, value, seen = {}, 0, {}
  for itemID, n in pairs(f.items or {}) do
    local unit, source = ns.ItemValue(itemID)
    value = value + unit * n
    list[#list + 1] = { id = itemID, name = ns.ItemName(itemID), count = n, unit = unit, total = unit * n,
                        source = source }
    seen[itemID] = true
  end
  -- Los objetos del farmeo que aún no han salido, a cero: así ves qué buscas.
  for _, itemID in ipairs(data and data.items or {}) do
    if not seen[itemID] then
      list[#list + 1] = { id = itemID, name = ns.ItemName(itemID), count = 0, total = 0 }
    end
  end
  table.sort(list, function(a, b)
    if a.total ~= b.total then return a.total > b.total end
    if a.count ~= b.count then return a.count > b.count end
    return a.name < b.name
  end)
  local elapsed = T.Elapsed(f)
  local total = (f.money or 0) + value
  return { items = list, value = value, money = f.money or 0, total = total, elapsed = elapsed,
           perHour = math.floor(total * 3600 / math.max(elapsed, MIN_SECONDS)) }
end

local function ItemCount(itemID, includeBank)
  local get = (C_Item and C_Item.GetItemCount) or GetItemCount
  return get and get(itemID, includeBank) or 0
end

-- Materiales para las fabricaciones previstas (las que el mercado absorbe en un día).
function T.CraftSummary(f, data)
  local n = f.crafts or (data and data.craftsDay) or 1
  local reagents, ready = {}, n
  for _, r in ipairs(data and data.reagents or {}) do
    local qty = r.qty or 1
    local entry = { name = r.name or (r.id and ns.ItemName(r.id)) or "?", need = qty * n }
    if r.id and r.src ~= "divisa" then
      entry.have = ItemCount(r.id, false)
      entry.bank = math.max(0, ItemCount(r.id, true) - entry.have)
      ready = math.min(ready, math.floor(entry.have / qty))
    end
    reagents[#reagents + 1] = entry
  end
  return { crafts = n, ready = math.max(0, ready), reagents = reagents }
end

-- Cambios -----------------------------------------------------------------------------------

function T.Changed()
  T.Refresh()
  if ns.Hunt then ns.Hunt.Update() end
  if ns.Arrow then ns.Arrow.Update() end
  if ns.Methods and ns.Methods.Refresh then ns.Methods.Refresh() end
end

function T.Activate(row)
  local key = T.KeyFor(row)
  if Find(key) then return end
  local list = T.List()
  if #list >= MAX_ACTIVE then
    ns.Print(("ya tienes %d farmeos activos: acaba alguno antes."):format(MAX_ACTIVE))
    return
  end
  local craft = row.recipe ~= nil
  list[#list + 1] = { key = key, kind = craft and "craft" or "farm", name = row.name, elapsed = 0, items = {},
                      money = 0, mobs = {}, crafts = craft and (row.craftsDay or 1) or nil }
  T.Open()
  T.Changed()
  if ns.Hunt then ns.Hunt.Activated() end
end

function T.Remove(key)
  local _, i = Find(key)
  if not i then return end
  table.remove(T.List(), i)
  T.Changed()
end

function T.StartStop(key)
  local f = Find(key)
  if not f then return end
  if f.started then
    f.elapsed = T.Elapsed(f)
    f.started = nil
  else
    f.started = time()
  end
  T.Changed()
end

function T.Reset(key)
  local f = Find(key)
  if not f then return end
  f.elapsed, f.items, f.money = 0, {}, 0
  if f.started then f.started = time() end
  T.Changed()
end

function T.Finish(key)
  local f = Find(key)
  if not f then return end
  if f.kind == "farm" then
    local s = T.FarmSummary(f, T.Data(f))
    if s.elapsed > 0 then
      ns.Print(("%s: %s en %s (%s por hora)."):format(f.name, ns.Money(s.total), ns.Session.Duration(s.elapsed),
        Silver(s.perHour)))
    end
  end
  T.Remove(key)
end

function T.SetCrafts(key, delta)
  local f = Find(key)
  if not f or f.kind ~= "craft" then return end
  f.crafts = math.max(1, (f.crafts or 1) + delta)
  T.Refresh()
end

-- Ventana -----------------------------------------------------------------------------------

local window, scroll, child, emptyText
local boxes = {}
local width = DEFAULT_WIDTH
local opened = {}   -- recuadros desplegados en esta sesión

local function Clock(seconds)
  local h, m, s = math.floor(seconds / 3600), math.floor(seconds % 3600 / 60), seconds % 60
  if h > 0 then return ("%d:%02d:%02d"):format(h, m, s) end
  return ("%d:%02d"):format(m, s)
end

local function TimerText(f)
  return (f.started and "|cff33dd33%s|r" or "|cff999999%s|r"):format(Clock(T.Elapsed(f)))
end

local function PriceText(item)
  if not item.source then return "|cff999999sin precio|r" end
  return ns.Money(item.unit) .. (item.source == "vendedor" and " |cff999999(v)|r" or "")
end

local function FarmLines(f, data, open)
  local s = T.FarmSummary(f, data)
  local body, extra = {}, {}
  if not f.started and s.elapsed == 0 then
    body[1] = "|cff999999Empieza solo con el primer botín, o pulsa Empezar.|r"
  else
    local head = ("|cffffd100%s|r · %s/h"):format(ns.Money(s.total), Silver(s.perHour))
    body[1] = head .. (f.started and "" or " |cff999999(en pausa)|r")
  end
  for i = 1, math.min(SHOWN_ITEMS, #s.items) do
    local it = s.items[i]
    body[#body + 1] = ("%s ×%d%s"):format(it.name, it.count, it.total > 0 and (" · " .. ns.Money(it.total)) or "")
  end
  if #s.items > SHOWN_ITEMS then body[#body + 1] = ("|cff999999y %d más|r"):format(#s.items - SHOWN_ITEMS) end
  if not open then return body, extra end

  if data and data.gph then
    extra[#extra + 1] = ("Esperado: ~%s/h%s"):format(Silver(data.gph), data.measured and " (lo que mediste)" or "")
  end
  for _, it in ipairs(s.items) do
    if it.count > 0 then
      extra[#extra + 1] = ("%s ×%d a %s = %s"):format(it.name, it.count, PriceText(it), ns.Money(it.total))
    end
  end
  if s.money > 0 then extra[#extra + 1] = "Monedas: " .. ns.Money(s.money) end
  if data and data.zone then extra[#extra + 1] = "Zona: " .. data.zone end
  if data and ns.Map then
    local c = ns.Map.Counts(f, data)
    local parts = {}
    if c.spawn > 0 then parts[#parts + 1] = c.spawn .. " sitios de bichos" end
    if c.node > 0 then parts[#parts + 1] = c.node .. " de cosas del mapa" end
    if c.seen > 0 then parts[#parts + 1] = c.seen .. " donde has matado tú" end
    if #parts > 0 then
      extra[#extra + 1] = "En el mapa (M): " .. table.concat(parts, ", ")
    elseif data.point then
      extra[#extra + 1] = "|cff999999En el mapa: solo la zona; apunto dónde matas sus bichos al lootearlos.|r"
    end
  end
  local mobs = ns.Hunt and ns.Hunt.Names(f) or {}
  if #mobs > 0 then
    extra[#extra + 1] = "Bichos: " .. table.concat(mobs, ", ")
  elseif data and data.point then
    extra[#extra + 1] = "|cff999999Bichos: los apunto al lootear sus objetos, o selecciona uno y pulsa Objetivo.|r"
  end
  if not data then extra[#extra + 1] = "|cff999999El motor ya no lo calcula.|r" end
  return body, extra
end

local function CraftLines(f, data, open)
  local s = T.CraftSummary(f, data)
  local body, extra = {}, {}
  body[1] = data and ("Puedes fabricar |cffffd100%d|r de %d"):format(s.ready, s.crafts)
    or "|cff999999El motor ya no lo calcula.|r"
  for _, r in ipairs(s.reagents) do
    if r.have then
      local color = r.have >= r.need and "ff33dd33" or (r.have > 0 and "ffffd11a" or "ffff4040")
      body[#body + 1] = ("%s |c%s%d/%d|r"):format(r.name, color, r.have, r.need)
    else
      body[#body + 1] = ("%s ×%d"):format(r.name, r.need)
    end
  end
  if not open or not data then return body, extra end

  if data.profit then
    extra[#extra + 1] = ("Beneficio: ~%s por unidad, ~%s las %d"):format(ns.Money(data.profit),
      ns.Money(data.profit * math.floor(s.crafts * (data.outputQty or 1) + 0.5)), s.crafts)
  end
  for _, r in ipairs(s.reagents) do
    if (r.bank or 0) > 0 then extra[#extra + 1] = ("En el banco: %s ×%d"):format(r.name, r.bank) end
  end
  if ns.Methods and ns.Methods.CraftSteps then
    local steps = ns.Methods.CraftSteps(data)
    for i, step in ipairs(steps) do extra[#extra + 1] = ("%d. %s"):format(i, step) end
  end
  return body, extra
end

local function TextHeight(fs, lines)
  local h = fs.GetStringHeight and fs:GetStringHeight()
  if type(h) ~= "number" or h <= 0 then h = lines * LINE end
  return h
end

local function CreateBox()
  local box = CreateFrame("Frame", nil, child, "BackdropTemplate")
  if box.SetBackdrop then
    box:SetBackdrop({
      bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
      edgeSize = 10,
      insets = { left = 2, right = 2, top = 2, bottom = 2 },
    })
    box:SetBackdropColor(0.12, 0.12, 0.12, 0.85)
  end

  box.header = CreateFrame("Button", nil, box)
  box.header:SetPoint("TOPLEFT", PAD, -5)
  box.header:SetPoint("TOPRIGHT", -PAD, -5)
  box.header:SetHeight(HEADER_HEIGHT)
  box.header:SetScript("OnClick", function() T.ToggleOpen(box.key) end)
  box.name = box.header:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
  box.name:SetPoint("LEFT")
  box.name:SetPoint("RIGHT", -48, 0)
  box.name:SetJustifyH("LEFT")
  if box.name.SetWordWrap then box.name:SetWordWrap(false) end
  box.timer = box.header:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  box.timer:SetPoint("RIGHT")

  box.body = box:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  box.body:SetPoint("TOPLEFT", box.header, "BOTTOMLEFT", 0, -2)
  box.body:SetJustifyH("LEFT")
  box.body:SetJustifyV("TOP")
  box.extra = box:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  box.extra:SetPoint("TOPLEFT", box.body, "BOTTOMLEFT", 0, -3)
  box.extra:SetJustifyH("LEFT")
  box.extra:SetJustifyV("TOP")

  local function Button(text, onClick)
    local b = CreateFrame("Button", nil, box, "UIPanelButtonTemplate")
    b:SetHeight(BUTTON_HEIGHT)
    b:SetText(text)
    b:SetScript("OnClick", function() onClick(box.key) end)
    return b
  end
  box.toggle = Button("Empezar", T.StartStop)
  box.reset = Button("Reiniciar", T.Reset)
  box.finish = Button("Acabar", T.Finish)
  box.target = Button("Objetivo", function(key)
    local f = Find(key)
    if f and ns.Hunt then ns.Hunt.ToggleTarget(f) end
  end)
  box.less = Button("-", function(key) T.SetCrafts(key, -1) end)
  box.more = Button("+", function(key) T.SetCrafts(key, 1) end)
  return box
end

local function LayoutBox(box, f, top)
  local data = T.Data(f)
  local open = opened[f.key]
  local inner = width - 2 * PAD - 12
  box.key = f.key
  box:ClearAllPoints()
  box:SetPoint("TOPLEFT", child, "TOPLEFT", 0, -top)
  box:SetWidth(width - 12)

  box.name:SetText((open and "- " or "+ ") .. (f.name or f.key))
  box.timer:SetText(TimerText(f))
  local body, extra
  if f.kind == "craft" then
    body, extra = CraftLines(f, data, open)
  else
    body, extra = FarmLines(f, data, open)
  end
  box.body:SetWidth(inner)
  box.body:SetText(table.concat(body, "\n"))
  local height = 5 + HEADER_HEIGHT + 2 + TextHeight(box.body, #body)
  if open and #extra > 0 then
    box.extra:SetWidth(inner)
    box.extra:SetText(table.concat(extra, "\n"))
    box.extra:Show()
    height = height + 3 + TextHeight(box.extra, #extra)
  else
    box.extra:SetText("")
    box.extra:Hide()
  end

  -- Fila de botones (y, desplegado, la de Objetivo o la de cuántos fabricar).
  local third = math.floor((inner - 8) / 3)
  box.toggle:SetText(f.started and "Parar" or "Empezar")
  box.toggle:SetWidth(third)
  box.reset:SetWidth(third)
  box.finish:SetWidth(third)
  box.toggle:ClearAllPoints()
  box.toggle:SetPoint("BOTTOMLEFT", PAD, 5)
  box.reset:ClearAllPoints()
  box.reset:SetPoint("LEFT", box.toggle, "RIGHT", 4, 0)
  box.finish:ClearAllPoints()
  box.finish:SetPoint("LEFT", box.reset, "RIGHT", 4, 0)
  box.target:Hide()
  box.less:Hide()
  box.more:Hide()
  local extraRow = false
  if open and f.kind == "farm" and data and (data.point or #(data.mobs or {}) > 0) then
    local hunting = ns.Hunt and ns.Hunt.IsTargetOf(f)
    box.target:SetText(hunting and "Quitar objetivo" or "Añadir objetivo")
    box.target:SetWidth(inner)
    box.target:ClearAllPoints()
    box.target:SetPoint("BOTTOMLEFT", PAD, 5 + BUTTON_HEIGHT + 3)
    box.target:Show()
    extraRow = true
  elseif open and f.kind == "craft" then
    box.less:SetWidth(28)
    box.more:SetWidth(28)
    box.less:ClearAllPoints()
    box.less:SetPoint("BOTTOMLEFT", PAD, 5 + BUTTON_HEIGHT + 3)
    box.more:ClearAllPoints()
    box.more:SetPoint("LEFT", box.less, "RIGHT", 4, 0)
    box.less:Show()
    box.more:Show()
    extraRow = true
  end
  height = height + 4 + BUTTON_HEIGHT + 5 + (extraRow and (BUTTON_HEIGHT + 3) or 0)
  box:SetHeight(height)
  box:Show()
  return height
end

function T.Refresh()
  if not window or not window:IsShown() then return end
  local list = T.List()
  local top = 0
  for i, f in ipairs(list) do
    boxes[i] = boxes[i] or CreateBox()
    top = top + LayoutBox(boxes[i], f, top) + BOX_GAP
  end
  for i = #list + 1, #boxes do
    boxes[i].key = nil
    boxes[i]:Hide()
  end
  if #list == 0 then
    emptyText:SetText("Elige farmeos en la ventana de métodos (botón «Farmear este» o «Craftear este»).")
    emptyText:Show()
  else
    emptyText:Hide()
  end
  child:SetHeight(math.max(top, 1))
  if scroll.SetVerticalScroll and scroll.GetHeight then
    local max = math.max(0, top - (scroll:GetHeight() or 0))
    scroll:SetVerticalScroll(math.min(scroll:GetVerticalScroll() or 0, max))
  end
end

-- Solo los relojes, cada segundo.
local function Tick()
  for _, box in ipairs(boxes) do
    local f = box:IsShown() and Find(box.key)
    if f then box.timer:SetText(TimerText(f)) end
  end
end

function T.ToggleOpen(key)
  opened[key] = not opened[key] or nil
  T.Refresh()
end

function T.AnyOpen()
  return window ~= nil and window:IsShown() and next(opened) ~= nil
end

local function Settings()
  PitiGoldsDB.ui.tracker = PitiGoldsDB.ui.tracker or {}
  return PitiGoldsDB.ui.tracker
end

local function SaveGeometry()
  local s = Settings()
  local point, _, relativePoint, x, y = window:GetPoint()
  s.point = { point, relativePoint, x, y }
  s.width, s.height = window:GetWidth(), window:GetHeight()
end

local function CreateWindow()
  local s = Settings()
  width = s.width or DEFAULT_WIDTH
  window = CreateFrame("Frame", "PitiGoldsTracker", UIParent, "BackdropTemplate")
  window:SetSize(width, s.height or DEFAULT_HEIGHT)
  if s.point then
    window:SetPoint(s.point[1], UIParent, s.point[2], s.point[3], s.point[4])
  else
    window:SetPoint("RIGHT", UIParent, "RIGHT", -40, 60)
  end
  window:SetFrameStrata("MEDIUM")
  window:SetMovable(true)
  window:SetResizable(true)
  if window.SetResizeBounds then
    window:SetResizeBounds(MIN_WIDTH, MIN_HEIGHT, MAX_WIDTH, MAX_HEIGHT)
  elseif window.SetMinResize then
    window:SetMinResize(MIN_WIDTH, MIN_HEIGHT)
    window:SetMaxResize(MAX_WIDTH, MAX_HEIGHT)
  end
  window:SetClampedToScreen(true)
  window:EnableMouse(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", function(self)
    self:StopMovingOrSizing()
    SaveGeometry()
  end)
  window:SetBackdrop({
    bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
    edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
    edgeSize = 12,
    insets = { left = 3, right = 3, top = 3, bottom = 3 },
  })
  window:SetBackdropColor(0, 0, 0, 0.6)

  local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", 8, -7)
  title:SetText("Farmeos activos")
  local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
  close:SetSize(22, 22)
  close:SetPoint("TOPRIGHT", 0, 0)
  close:SetScript("OnClick", function()
    window:Hide()
    Settings().hidden = true
  end)

  scroll = CreateFrame("ScrollFrame", nil, window)
  scroll:SetPoint("TOPLEFT", PAD, -24)
  scroll:SetPoint("BOTTOMRIGHT", -PAD, 14)
  child = CreateFrame("Frame", nil, scroll)
  child:SetSize(width - 12, 1)
  scroll:SetScrollChild(child)
  scroll:EnableMouseWheel(true)
  scroll:SetScript("OnMouseWheel", function(self, delta)
    local max = math.max(0, (child:GetHeight() or 0) - (self:GetHeight() or 0))
    local current = self:GetVerticalScroll() or 0
    self:SetVerticalScroll(math.max(0, math.min(max, current - delta * 30)))
  end)
  emptyText = child:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  emptyText:SetPoint("TOPLEFT", 2, -2)
  emptyText:SetWidth(width - 16)
  emptyText:SetJustifyH("LEFT")

  -- Agarradera para cambiar el tamaño.
  local grip = CreateFrame("Button", nil, window)
  grip:SetSize(14, 14)
  grip:SetPoint("BOTTOMRIGHT", -2, 2)
  grip:SetNormalTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Up")
  grip:SetHighlightTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Highlight")
  grip:SetPushedTexture("Interface\\ChatFrame\\UI-ChatIM-SizeGrabber-Down")
  -- Antes de redimensionar se ancla por la esquina de arriba a la izquierda, que es la que se queda
  -- quieta: anclada por el lado derecho (como sale la primera vez), WoW la hace crecer de golpe al
  -- empezar a tirar.
  grip:SetScript("OnMouseDown", function()
    local left, top = window:GetLeft(), window:GetTop()
    if left and top then
      window:ClearAllPoints()
      window:SetPoint("TOPLEFT", UIParent, "BOTTOMLEFT", left, top)
    end
    window:StartSizing("BOTTOMRIGHT")
  end)
  grip:SetScript("OnMouseUp", function()
    window:StopMovingOrSizing()
    SaveGeometry()
  end)

  window:SetScript("OnSizeChanged", function(_, w)
    if type(w) == "number" and w > 0 then
      width = w
      child:SetWidth(w - 12)
      emptyText:SetWidth(w - 16)
      T.Refresh()
    end
  end)

  local sinceTick, sinceRefresh = 0, 0
  window:SetScript("OnUpdate", function(_, elapsed)
    sinceTick, sinceRefresh = sinceTick + elapsed, sinceRefresh + elapsed
    if sinceRefresh >= 15 then
      sinceTick, sinceRefresh = 0, 0
      T.Refresh()          -- el oro por hora baja con el tiempo aunque no entre nada
    elseif sinceTick >= 1 then
      sinceTick = 0
      Tick()
    end
  end)
end

function T.Open()
  if not window then CreateWindow() end
  window:Show()
  Settings().hidden = nil
  T.Refresh()
end

function T.Toggle()
  if window and window:IsShown() then
    window:Hide()
    Settings().hidden = true
  else
    T.Open()
  end
end

function T.IsShown()
  return window ~= nil and window:IsShown()
end

-- Para las pruebas: el texto de cada recuadro.
function T.BoxTexts()
  local out = {}
  for _, box in ipairs(boxes) do
    if box:IsShown() then
      out[#out + 1] = table.concat({ box.name:GetText() or "", box.timer:GetText() or "", box.body:GetText() or "",
                                     box.extra:GetText() or "" }, "\n")
    end
  end
  return table.concat(out, "\n---\n")
end

-- Al salir se paran los relojes; al volver siguen si fue un /reload o un cambio rápido de
-- personaje, sin contar el rato fuera. Si pasó más tiempo, quedan en pausa.
function T.OnLogout()
  local now = time()
  for _, f in ipairs(T.List()) do
    if f.started then
      f.elapsed = T.Elapsed(f)
      f.started, f.stoppedAt = nil, now
    end
  end
end

function T.OnLogin()
  local now = time()
  for _, f in ipairs(T.List()) do
    local stopped = f.stoppedAt or f.started
    f.started, f.stoppedAt = nil, nil
    if stopped and now - stopped <= RESUME_WITHIN then f.started = now end
  end
  if #T.List() > 0 and not Settings().hidden then T.Open() end
end

ns.On("PLAYER_LOGOUT", T.OnLogout)
ns.On("PLAYER_LOGIN", T.OnLogin)

ns.On("PLAYER_TARGET_CHANGED", function()
  if T.AnyOpen() then T.Refresh() end
end)

ns.On("BAG_UPDATE_DELAYED", function()
  -- Los materiales de los crafteos cambian también con el banco, el correo o la subasta.
  if T.IsShown() then ns.Debounce("tracker", 0.5, T.Refresh) end
end)

ns.Command("activos", "muestra u oculta la ventana de farmeos activos", T.Toggle)
