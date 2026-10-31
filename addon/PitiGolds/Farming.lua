-- Registro de farmeos: apunta lo que ganas (objetos que entran en las bolsas y oro) en
-- tramos de 5 minutos por zona, para que el motor calcule tu oro por hora real en cada
-- sitio y actividad. Mientras hay farmeos activos en marcha, el tramo lleva su id. No cuenta lo que entra con el correo, la subasta, el banco, un
-- vendedor, un intercambio o la ventana de una profesión abiertos: eso no es lo farmeado.
local ADDON, ns = ...

local BUCKET_SECONDS = 300
local MAX_BUCKETS = 2000

local pauses = {}   -- motivo -> true
local snapshot      -- objetos en las bolsas la última vez que se miró
local lastMoney

local function CountCarried()
  local counts = {}
  local lastCarried = NUM_TOTAL_EQUIPPED_BAG_SLOTS or ((NUM_BAG_SLOTS or 4) + 1)
  for bag = 0, lastCarried do
    for slot = 1, C_Container.GetContainerNumSlots(bag) or 0 do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID then
        counts[info.itemID] = (counts[info.itemID] or 0) + (info.stackCount or 1)
      end
    end
  end
  return counts
end

local function Paused()
  return next(pauses) ~= nil
end

local function CurrentZone()
  local mapID = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player") or 0
  local info = mapID ~= 0 and C_Map.GetMapInfo and C_Map.GetMapInfo(mapID)
  return mapID, (info and info.name) or (GetZoneText and GetZoneText()) or "?"
end

-- Tramo de 5 minutos de esta zona y etiqueta; se crea al ganar algo.
local function Bucket()
  local now = time()
  local start = now - now % BUCKET_SECONDS
  local mapID, zoneName = CurrentZone()
  local label = (ns.Tracker and ns.Tracker.Label()) or PitiGoldsDB.farmLabel
  local key = table.concat({ start, ns.charKey or "?", mapID, label or "" }, "|")
  local log = PitiGoldsDB.farmLog
  local b = log[key]
  if not b then
    b = { t = start, char = ns.charKey, zone = mapID, zoneName = zoneName, label = label,
          items = {}, money = 0, first = now }
    log[key] = b
  end
  b.last = now
  return b
end

local function OnBagsChanged()
  local counts = CountCarried()
  if snapshot and not Paused() then
    local gains, b, tracked = {}, nil, false
    for itemID, n in pairs(counts) do
      local gained = n - (snapshot[itemID] or 0)
      if gained > 0 then gains[itemID] = gained end
    end
    -- Antes que el tramo: el primer botín pone en marcha el farmeo activo que lo espera, y así
    -- el tramo ya lleva su id.
    for itemID, gained in pairs(gains) do
      if ns.Tracker and ns.Tracker.AddItem(itemID, gained) then tracked = true end
    end
    for itemID, gained in pairs(gains) do
      b = b or Bucket()
      b.items[itemID] = (b.items[itemID] or 0) + gained
      if ns.Session then ns.Session.AddItem(itemID, gained) end
    end
    -- El panel se pone al día en cuanto entra algo, sin esperar a nada.
    if b and ns.RefreshUI then ns.RefreshUI() end
    if tracked then ns.Tracker.Changed() end
  end
  snapshot = counts
end

local function OnMoneyChanged()
  local money = GetMoney()
  if lastMoney and money > lastMoney and not Paused() then
    local b = Bucket()
    b.money = b.money + (money - lastMoney)
    if ns.Session then ns.Session.AddMoney(money - lastMoney) end
    if ns.Tracker then ns.Tracker.AddMoney(money - lastMoney) end
    lastMoney = money
    if ns.RefreshUI then ns.RefreshUI() end
  else
    lastMoney = money
  end
end

local function Pause(reason)
  if not Paused() then
    -- Lo que llegó justo antes de abrir la ventana sí es farmeado.
    OnBagsChanged()
    OnMoneyChanged()
  end
  pauses[reason] = true
end

local function Resume(reason)
  if not pauses[reason] then return end
  pauses[reason] = nil
  if not Paused() then
    -- Lo que entró durante la pausa no cuenta: se vuelve a tomar referencia.
    snapshot = CountCarried()
    lastMoney = GetMoney()
  end
end

-- Pausas -----------------------------------------------------------------------------

local WINDOWS = {
  { "MAIL_SHOW", "MAIL_CLOSED", "correo" },
  { "AUCTION_HOUSE_SHOW", "AUCTION_HOUSE_CLOSED", "subasta" },
  { "BANKFRAME_OPENED", "BANKFRAME_CLOSED", "banco" },
  { "MERCHANT_SHOW", "MERCHANT_CLOSED", "vendedor" },
  { "TRADE_SHOW", "TRADE_CLOSED", "intercambio" },
  { "TRADE_SKILL_SHOW", "TRADE_SKILL_CLOSE", "profesion" },
}
for _, w in ipairs(WINDOWS) do
  local reason = w[3]
  -- Si el evento de cierre no existe en este cliente, mejor no pausar nunca que quedarse en pausa.
  if ns.On(w[2], function() Resume(reason) end) then
    ns.On(w[1], function() Pause(reason) end)
  end
end

local function InteractionReason(kind)
  local P = Enum and Enum.PlayerInteractionType
  if not P then return nil end
  if kind == P.MailInfo then return "correo" end
  if kind == P.Auctioneer then return "subasta" end
  if kind == P.Merchant then return "vendedor" end
  if kind == P.TradePartner then return "intercambio" end
  if kind == P.Banker or kind == P.AccountBanker or kind == P.CharacterBanker or kind == P.GuildBanker then
    return "banco"
  end
end

ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  local reason = InteractionReason(kind)
  if reason then Pause(reason) end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  local reason = InteractionReason(kind)
  if reason then Resume(reason) end
end)

ns.On("BAG_UPDATE_DELAYED", function() ns.Debounce("farm", 0.5, OnBagsChanged) end)
ns.On("PLAYER_MONEY", OnMoneyChanged)

-- Limpieza: fuera lo que el motor ya ha guardado y, si aun así hay demasiado, lo más viejo.
local function Prune()
  local log = PitiGoldsDB.farmLog
  local gen = PitiGoldsGenerated
  local upTo = (type(gen) == "table" and tonumber(gen.farmIngestedUpTo)) or 0
  local keys = {}
  for key, b in pairs(log) do
    if (b.t or 0) <= upTo then
      log[key] = nil
    else
      keys[#keys + 1] = key
    end
  end
  if #keys > MAX_BUCKETS then
    table.sort(keys, function(a, b) return log[a].t < log[b].t end)
    for i = 1, #keys - MAX_BUCKETS do log[keys[i]] = nil end
  end
end

ns.On("PLAYER_LOGIN", function()
  Prune()
  lastMoney = GetMoney()
  -- Las bolsas tardan un momento en estar listas al entrar.
  C_Timer.After(3, function() snapshot = CountCarried() end)
end)

-- Lo ganado en la última hora, valorado como la sesión (ns.ItemValue, en Session.lua).
function ns.FarmLastHour()
  local since = time() - 3600
  local money, value, first = 0, 0, nil
  for _, b in pairs(PitiGoldsDB.farmLog or {}) do
    if b.char == ns.charKey and (b.last or 0) >= since then
      money = money + (b.money or 0)
      first = math.min(first or b.first, b.first)
      for itemID, n in pairs(b.items) do
        value = value + (ns.ItemValue(itemID) or 0) * n
      end
    end
  end
  if not first then return nil end
  local hours = math.max(time() - first, BUCKET_SECONDS) / 3600
  return math.floor((money + value) / hours), money, value
end

ns.Command("farmeo", "pone nombre a lo que farmeas (/pg farmeo Cobre en Durotar; /pg farmeo fin)", function(text)
  text = ns.Trim(text or "")
  if text == "" then
    local perHour = ns.FarmLastHour()
    ns.Print(("farmeo: %s"):format(PitiGoldsDB.farmLabel or "sin nombre"))
    if perHour then ns.Print("última hora: " .. ns.Money(perHour) .. " por hora") end
  elseif text:lower() == "fin" then
    PitiGoldsDB.farmLabel = nil
    ns.Print("farmeo sin nombre a partir de ahora.")
  else
    PitiGoldsDB.farmLabel = text
    ns.Print("farmeando: " .. text)
  end
  if ns.RefreshUI then ns.RefreshUI() end
end)
