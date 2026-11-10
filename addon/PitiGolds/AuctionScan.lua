-- Escáner de la casa de subastas.
--   Completo: toda la subasta, una por una (C_AuctionHouse.ReplicateItems).
--             El servidor solo lo permite cada 15 minutos.
--   Materiales: recorre las categorías de profesiones y consumibles y guarda el
--             precio mínimo y la cantidad total de cada objeto, incluidos los
--             que se venden por unidades (commodities).
-- También apunta las subastas que tiene puestas el personaje.
local ADDON, ns = ...

local REPLICATE_COOLDOWN = 15 * 60
local BOOK_LEVELS = 10           -- niveles de precio que se guardan por objeto
local BROWSE_STALL_SECONDS = 20  -- sin respuesta durante este tiempo se pasa a la siguiente categoría

local Scan = { state = "idle", token = 0 }
ns.Scan = Scan

local function Money(n)
  return ("%.0f"):format(n)
end

local function Cancel(reason)
  if Scan.state == "idle" then return end
  Scan.state = "idle"
  Scan.token = Scan.token + 1
  Scan.pendingSend = nil
  if reason then ns.Print(reason) end
  if ns.RefreshUI then ns.RefreshUI() end
end

local function Finish(kind, items, count)
  ns.AddScan({
    type = kind,
    time = time(),
    started = Scan.startedAt,
    duration = time() - Scan.startedAt,
    realm = GetRealmName(),
    faction = UnitFactionGroup("player"),
    char = ns.charKey,
    count = count,
    items = items,
  })
  Scan.state = "idle"
  Scan.token = Scan.token + 1
  ns.Log(("Escaneo %s: %d objetos en %d s"):format(kind, count, time() - Scan.startedAt))
  ns.Print(("escaneo %s terminado: %d objetos en %d s. Se guarda al cambiar de personaje, al salir o con /reload.")
    :format(kind == "full" and "completo" or "de materiales", count, time() - Scan.startedAt))
  if ns.RefreshUI then ns.RefreshUI() end
end

local function CanStart()
  if Scan.state ~= "idle" then
    ns.Print("ya hay un escaneo en marcha.")
    return false
  end
  if not ns.ahOpen then
    ns.Print("abre la casa de subastas primero.")
    return false
  end
  return true
end

-- Escaneo completo ------------------------------------------------------------------

local function CompactBook(a)
  local prices = {}
  for p in pairs(a.book) do prices[#prices + 1] = p end
  table.sort(prices)
  local parts = {}
  for i = 1, math.min(#prices, BOOK_LEVELS) do
    parts[i] = Money(prices[i]) .. ":" .. a.book[prices[i]]
  end
  -- mínimo,cantidad,subastas,vendedores|precio:cantidad;precio:cantidad...
  return ("%s,%d,%d,%d|%s"):format(Money(a.min), a.qty, a.n, a.nOwners, table.concat(parts, ";"))
end

local function ProcessReplicate(total)
  Scan.state = "full_process"
  local token = Scan.token
  local agg = {}
  ns.RunChunked(total, 2000, function(k)
    if Scan.token ~= token then return end
    -- Orden de valores: name, texture, count, qualityID, usable, level, levelType,
    -- minBid, minIncrement, buyoutPrice, bidAmount, highBidder, bidderFullName,
    -- owner, ownerFullName, saleStatus, itemID, hasAllInfo
    local _, _, count, _, _, _, _, _, _, buyout, _, _, _, owner, _, _, itemID =
      C_AuctionHouse.GetReplicateItemInfo(k - 1)
    if itemID and buyout and buyout > 0 and count and count > 0 then
      local unit = math.floor(buyout / count)
      local a = agg[itemID]
      if not a then
        a = { min = unit, qty = 0, n = 0, book = {}, owners = {}, nOwners = 0 }
        agg[itemID] = a
      end
      a.qty = a.qty + count
      a.n = a.n + 1
      if unit < a.min then a.min = unit end
      a.book[unit] = (a.book[unit] or 0) + count
      if owner and owner ~= "" and not a.owners[owner] then
        a.owners[owner] = true
        a.nOwners = a.nOwners + 1
      end
    end
  end, function()
    if Scan.token ~= token then return end
    local items, count = {}, 0
    for itemID, a in pairs(agg) do
      items[itemID] = CompactBook(a)
      count = count + 1
    end
    Finish("full", items, count)
  end, "escaneo completo", function()
    Cancel("el escaneo completo ha fallado; mira /pg log.")
  end)
end

function Scan.StartFull()
  if not CanStart() then return end
  local remaining = (PitiGoldsDB.lastReplicate or 0) + REPLICATE_COOLDOWN - time()
  if remaining > 0 then
    ns.Print(("el escaneo completo solo se puede hacer cada 15 minutos. Faltan %d:%02d.")
      :format(math.floor(remaining / 60), remaining % 60))
    return
  end
  Scan.state = "full_wait"
  Scan.token = Scan.token + 1
  Scan.startedAt = time()
  PitiGoldsDB.lastReplicate = time()
  C_AuctionHouse.ReplicateItems()
  ns.Print("escaneo completo pedido al servidor; tarda un poco, no cierres la subasta.")
  if ns.RefreshUI then ns.RefreshUI() end
  local token = Scan.token
  C_Timer.After(90, function()
    if Scan.token == token and Scan.state == "full_wait" then
      Cancel("el servidor no respondió al escaneo completo.")
    end
  end)
end

-- Cuando llega la lista se espera a que el número de subastas deje de cambiar.
ns.On("REPLICATE_ITEM_LIST_UPDATE", function()
  if Scan.state ~= "full_wait" then return end
  Scan.state = "full_settle"
  local token = Scan.token
  local last, stable = -1, 0
  local function check()
    if Scan.token ~= token then return end
    local n = C_AuctionHouse.GetNumReplicateItems()
    if n == last then stable = stable + 1 else stable, last = 0, n end
    if stable >= 2 then
      ProcessReplicate(n)
    else
      C_Timer.After(0.5, check)
    end
  end
  check()
end)

-- Escaneo de materiales ---------------------------------------------------------------

local function MaterialClasses()
  local E = (Enum and Enum.ItemClass) or {}
  return {
    E.Tradegoods or 7, E.Reagent or 5, E.Consumable or 0, E.Recipe or 9,
    E.Gem or 3, E.ItemEnhancement or 8, E.Profession or 19,
  }
end

-- Envía la petición en cuanto el servidor de subastas acepte mensajes.
local function SendWhenReady(fn)
  if not C_AuctionHouse.IsThrottledMessageSystemReady or C_AuctionHouse.IsThrottledMessageSystemReady() then
    fn()
  else
    Scan.pendingSend = fn
  end
end

ns.AuctionSendWhenReady = SendWhenReady

ns.On("AUCTION_HOUSE_THROTTLED_SYSTEM_READY", function()
  local fn = Scan.pendingSend
  if fn then
    Scan.pendingSend = nil
    fn()
  end
end)

local function CollectBrowse()
  local results = C_AuctionHouse.GetBrowseResults() or {}
  for _, r in ipairs(results) do
    local itemID = r.itemKey and r.itemKey.itemID
    if itemID and r.minPrice and r.minPrice > 0 then
      local a = Scan.browseItems[itemID]
      if not a then
        a = { min = r.minPrice, qty = 0 }
        Scan.browseItems[itemID] = a
      end
      if r.minPrice < a.min then a.min = r.minPrice end
      a.qty = a.qty + (r.totalQuantity or 0)
    end
  end
end

local NextClass

local function FinishBrowse()
  local items, count = {}, 0
  for itemID, a in pairs(Scan.browseItems) do
    items[itemID] = Money(a.min) .. "," .. a.qty
    count = count + 1
  end
  Scan.browseItems = nil
  Finish("browse", items, count)
end

NextClass = function()
  Scan.classIndex = Scan.classIndex + 1
  local classID = Scan.classes[Scan.classIndex]
  if classID == nil then
    FinishBrowse()
    return
  end
  Scan.lastCount = -1
  Scan.lastProgress = GetTime()
  SendWhenReady(function()
    C_AuctionHouse.SendBrowseQuery({
      searchString = "",
      sorts = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } },
      filters = {},
      itemClassFilters = { { classID = classID } },
    })
  end)
end

local function AdvanceBrowse()
  if Scan.state ~= "browse" then return end
  local results = C_AuctionHouse.GetBrowseResults() or {}
  Scan.lastProgress = GetTime()
  if C_AuctionHouse.HasFullBrowseResults() then
    CollectBrowse()
    NextClass()
  elseif #results > Scan.lastCount then
    Scan.lastCount = #results
    SendWhenReady(C_AuctionHouse.RequestMoreBrowseResults)
  end
end

-- Tus búsquedas ------------------------------------------------------------------------
-- Lo que sale al buscar en la subasta (a mano, con el botón Buscar o desde otro addon) se apunta
-- en un escaneo «search», uno por visita a la subasta, que se va completando. El tooltip y la
-- ventana de profesión lo usan al momento y el motor lo lee como cualquier otro escaneo.
local search          -- el escaneo de esta visita
local searchExact = {} -- objetos con su lista de subastas entera: un mínimo suelto no los pisa

local function SearchScan()
  if not search then
    local now = time()
    search = {
      type = "search", time = now, started = now, duration = 0,
      realm = GetRealmName(), faction = UnitFactionGroup("player"), char = ns.charKey,
      count = 0, items = {},
    }
    ns.AddScan(search)
  end
  return search
end

local function NoteSearch(itemID, text, exact)
  if not exact and searchExact[itemID] then return end
  local s = SearchScan()
  if s.items[itemID] == nil then s.count = s.count + 1 end
  s.items[itemID] = text
  if exact then searchExact[itemID] = true end
  s.time = time()
  s.duration = s.time - s.started
  if ns.InvalidateScanPrices then ns.InvalidateScanPrices() end
  ns.Debounce("ahlive", 0.3, function()
    if ns.OnLivePrices then ns.OnLivePrices() end
  end)
end

-- "mínimo,cantidad,subastas|precio:cantidad;..." como el escaneo completo, sin vendedores.
local function BookText(book, min, qty, n)
  local prices = {}
  for p in pairs(book) do prices[#prices + 1] = p end
  table.sort(prices)
  local parts = {}
  for i = 1, math.min(#prices, BOOK_LEVELS) do
    parts[i] = Money(prices[i]) .. ":" .. book[prices[i]]
  end
  return ("%s,%d,%d|%s"):format(Money(min), qty, n, table.concat(parts, ";"))
end

-- Lista de resultados: el precio mínimo y la cantidad de cada objeto.
local function RecordBrowse()
  if Scan.state ~= "idle" then return end
  local found = {}
  for _, r in ipairs(C_AuctionHouse.GetBrowseResults() or {}) do
    local key = r.itemKey
    if key and key.itemID and (key.battlePetSpeciesID or 0) == 0 and r.minPrice and r.minPrice > 0 then
      local a = found[key.itemID]
      if not a then
        found[key.itemID] = { min = r.minPrice, qty = r.totalQuantity or 0 }
      else
        a.min = math.min(a.min, r.minPrice)
        a.qty = a.qty + (r.totalQuantity or 0)
      end
    end
  end
  for itemID, a in pairs(found) do
    NoteSearch(itemID, Money(a.min) .. "," .. a.qty, false)
  end
end

-- Al abrir un objeto que se vende por unidades: todas sus subastas, precio a precio.
local function RecordCommodity(itemID)
  local AH = C_AuctionHouse
  if not (itemID and AH.GetNumCommoditySearchResults and AH.GetCommoditySearchResultInfo) then return end
  local book, min, qty, n = {}, nil, 0, 0
  for i = 1, AH.GetNumCommoditySearchResults(itemID) or 0 do
    local r = AH.GetCommoditySearchResultInfo(itemID, i)
    if r and r.unitPrice and r.unitPrice > 0 and (r.quantity or 0) > 0 then
      book[r.unitPrice] = (book[r.unitPrice] or 0) + r.quantity
      qty, n = qty + r.quantity, n + 1
      if not min or r.unitPrice < min then min = r.unitPrice end
    end
  end
  if min then NoteSearch(itemID, BookText(book, min, qty, n), true) end
end

-- Al abrir un objeto que se vende suelto: cada subasta con su precio por unidad.
local function RecordItem(itemKey)
  local AH = C_AuctionHouse
  local itemID = type(itemKey) == "table" and itemKey.itemID
  if not (itemID and AH.GetNumItemSearchResults and AH.GetItemSearchResultInfo) then return end
  local book, min, qty, n = {}, nil, 0, 0
  for i = 1, AH.GetNumItemSearchResults(itemKey) or 0 do
    local r = AH.GetItemSearchResultInfo(itemKey, i)
    local count = r and r.quantity or 0
    if r and r.buyoutAmount and r.buyoutAmount > 0 and count > 0 then
      local unit = math.floor(r.buyoutAmount / count)
      book[unit] = (book[unit] or 0) + count
      qty, n = qty + count, n + 1
      if not min or unit < min then min = unit end
    end
  end
  if min then NoteSearch(itemID, BookText(book, min, qty, n), true) end
end

ns.On("COMMODITY_SEARCH_RESULTS_UPDATED", function(_, itemID)
  if Scan.state ~= "idle" or not itemID then return end
  ns.Debounce("ahcommodity" .. itemID, 0.3, function() RecordCommodity(itemID) end)
end)
ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(_, itemKey)
  if Scan.state ~= "idle" or type(itemKey) ~= "table" or not itemKey.itemID then return end
  ns.Debounce("ahitem" .. itemKey.itemID, 0.3, function() RecordItem(itemKey) end)
end)

local function OnBrowseEvent()
  if Scan.state == "browse" then
    ns.Debounce("ahbrowse", 0.3, AdvanceBrowse)
  elseif Scan.state == "idle" and ns.ahOpen then
    ns.Debounce("ahsearch", 0.3, RecordBrowse)
  end
end
ns.On("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED", OnBrowseEvent)
ns.On("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", OnBrowseEvent)

-- Si una categoría deja de responder se guarda lo que haya llegado y se sigue.
local function Watchdog(token)
  if Scan.token ~= token or Scan.state ~= "browse" then return end
  if GetTime() - Scan.lastProgress > BROWSE_STALL_SECONDS then
    ns.Log("Escaneo de materiales: la categoría " .. tostring(Scan.classes[Scan.classIndex]) .. " no respondió")
    CollectBrowse()
    NextClass()
  end
  C_Timer.After(2, function() Watchdog(token) end)
end

function Scan.StartMaterials()
  if not CanStart() then return end
  Scan.state = "browse"
  Scan.token = Scan.token + 1
  Scan.startedAt = time()
  Scan.classes = MaterialClasses()
  Scan.classIndex = 0
  Scan.browseItems = {}
  ns.Print("escaneando materiales y consumibles; no toques la subasta mientras tanto.")
  if ns.RefreshUI then ns.RefreshUI() end
  NextClass()
  Watchdog(Scan.token)
end

function Scan.Status()
  if Scan.state == "idle" then return nil end
  if Scan.state == "browse" then
    return ("materiales %d/%d"):format(Scan.classIndex or 0, #(Scan.classes or {}))
  end
  return "completo en curso"
end

-- Subastas propias ---------------------------------------------------------------------

local function RecordOwnedAuctions()
  if not C_AuctionHouse.GetNumOwnedAuctions then return end
  local list = {}
  for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
    local a = C_AuctionHouse.GetOwnedAuctionInfo(i)
    if a and a.itemKey then
      list[#list + 1] = {
        itemID = a.itemKey.itemID,
        qty = a.quantity,
        buyout = a.buyoutAmount,
        bid = a.bidAmount,
        status = a.status,
        timeLeft = a.timeLeftSeconds,
      }
      ns.NoteItem(a.itemKey.itemID, a.itemLink and a.itemLink:match("%[(.-)%]"))
    end
  end
  ns.Char().inventory.auctions = { list = list, updated = time() }
end

ns.On("OWNED_AUCTIONS_UPDATED", RecordOwnedAuctions)

-- Apertura y cierre de la subasta -------------------------------------------------------

local function OnAuctionHouseOpened()
  if ns.ahOpen then return end
  ns.ahOpen = true
  if ns.ShowAuctionButtons then ns.ShowAuctionButtons() end
  C_Timer.After(1, function()
    if ns.ahOpen and Scan.state == "idle" and C_AuctionHouse.QueryOwnedAuctions then
      pcall(C_AuctionHouse.QueryOwnedAuctions, {})
    end
  end)
end

local function OnAuctionHouseClosed()
  if not ns.ahOpen then return end
  ns.ahOpen = false
  search, searchExact = nil, {}  -- la próxima visita empieza otro escaneo de búsquedas
  Cancel(Scan.state ~= "idle" and "escaneo cancelado al cerrar la subasta." or nil)
  if ns.HideAuctionButtons then ns.HideAuctionButtons() end
end

local function IsAuctionInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and kind == P.Auctioneer
end

ns.On("AUCTION_HOUSE_SHOW", OnAuctionHouseOpened)
ns.On("AUCTION_HOUSE_CLOSED", OnAuctionHouseClosed)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsAuctionInteraction(kind) then OnAuctionHouseOpened() end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  if IsAuctionInteraction(kind) then OnAuctionHouseClosed() end
end)

ns.Command("completo", "escaneo completo de la subasta (cada 15 min)", function() Scan.StartFull() end)
ns.Command("materiales", "escaneo de materiales y consumibles", function() Scan.StartMaterials() end)
