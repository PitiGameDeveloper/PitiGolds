-- Escáner de la casa de subastas.
--   Completo: toda la subasta, una por una (C_AuctionHouse.ReplicateItems). Se hace solo al abrir
--             la subasta si el último tiene más de AUTO_EVERY (/pg auto lo apaga). Es una sola
--             petición al servidor, así que no choca con tus búsquedas: se siguen apuntando.
--             Si otro addon (Auctionator) pide la subasta entera, también se aprovecha.
--   Materiales: recorre las categorías de profesiones y consumibles y guarda el
--             precio mínimo y la cantidad total de cada objeto, incluidos los
--             que se venden por unidades (commodities).
-- También apunta las subastas que tiene puestas el personaje.
local ADDON, ns = ...

local BOOK_LEVELS = 10           -- niveles de precio que se guardan por objeto
local BROWSE_STALL_SECONDS = 20  -- sin respuesta durante este tiempo se pasa a la siguiente categoría
local AUTO_DELAY = 5             -- segundos tras abrir la subasta antes del escaneo automático
local AUTO_EVERY = 15 * 60       -- como mucho un escaneo automático cada 15 minutos
-- El servidor solo atiende un ReplicateItems cada 15 minutos por cuenta (también los de
-- Auctionator): si se pide antes, no contesta nada.
local REPLICATE_EVERY = 15 * 60
local FULL_TIMEOUT = 180         -- un completo de un reino lleno ha llegado a tardar 88 s

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
  if kind == "full" then PitiGoldsDB.lastFull = time() end
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

-- Cualquier petición de la subasta entera, la nuestra o la de otro addon, cuenta para el límite.
if C_AuctionHouse and C_AuctionHouse.ReplicateItems then
  hooksecurefunc(C_AuctionHouse, "ReplicateItems", function()
    PitiGoldsDB.lastFullRequest = time()
  end)
end

-- Segundos hasta que el servidor vuelva a atender un completo (0: ya se puede pedir).
local function ReplicateWait()
  return math.max(0, (PitiGoldsDB.lastFullRequest or 0) + REPLICATE_EVERY - time())
end

-- El servidor contestó a la última petición pero no se guardó (se cerró la subasta a medias):
-- el cliente conserva la lista, así que se aprovecha sin pedir otra. Si no contestó, lo que
-- tenga el cliente es el completo anterior, ya guardado.
local function PendingReplicate()
  local reply = PitiGoldsDB.lastFullReply or 0
  return reply >= (PitiGoldsDB.lastFullRequest or 0) and reply > (PitiGoldsDB.lastFull or 0)
    and C_AuctionHouse.GetNumReplicateItems() > 0
end

local Settle

local function Adopt(why)
  Scan.token = Scan.token + 1
  Scan.startedAt = time()
  Scan.state = "full_wait"
  ns.Log("Escaneo completo: " .. why)
  Settle()
end

function Scan.StartFull(auto)
  if not CanStart() then return end
  if ReplicateWait() > 0 then
    if PendingReplicate() then
      ns.Print("guardando el escaneo completo que ya había llegado; tarda un poco.")
      Adopt("se aprovecha la lista que ya había llegado")
    elseif not auto then
      ns.Print(("el servidor solo da un escaneo completo cada 15 minutos (cuenta también Auctionator);"
        .. " el último se pidió hace %d min. Vuelve a probar a las %s."):format(
        math.floor((REPLICATE_EVERY - ReplicateWait()) / 60), date("%H:%M", time() + ReplicateWait())))
    end
    return
  end
  Scan.state = "full_wait"
  Scan.token = Scan.token + 1
  Scan.startedAt = time()
  C_AuctionHouse.ReplicateItems()
  ns.Print((auto and "escaneo completo automático en marcha" or "escaneo completo pedido al servidor")
    .. "; tarda un poco. Puedes buscar y comprar mientras tanto; si cierras la subasta, se guarda al volver.")
  if ns.RefreshUI then ns.RefreshUI() end
  local token = Scan.token
  C_Timer.After(FULL_TIMEOUT, function()
    if Scan.token == token and Scan.state == "full_wait" then
      Cancel(("el servidor no respondió al escaneo completo. Si llega más tarde se guarda solo;"
        .. " si no, se puede volver a pedir a las %s."):format(date("%H:%M", time() + ReplicateWait())))
    end
  end)
end

-- Cuando llega la lista se espera a que el número de subastas deje de cambiar.
ns.On("REPLICATE_ITEM_LIST_UPDATE", function()
  PitiGoldsDB.lastFullReply = time()
  if Scan.state == "idle" and ns.ahOpen and time() - (PitiGoldsDB.lastFull or 0) > 60 then
    -- Lo ha pedido otro addon (el botón de escanear de Auctionator) o ha llegado tarde: se aprovecha.
    Adopt("pedido por otro addon o llegado tarde: se aprovecha")
  elseif Scan.state == "full_wait" then
    Settle()
  end
end)

function Settle()
  Scan.state = "full_settle"
  local token = Scan.token
  local last, stable = -1, 0
  local function check()
    if Scan.token ~= token then return end
    local n = C_AuctionHouse.GetNumReplicateItems()
    if n == last then stable = stable + 1 else stable, last = 0, n end
    if stable >= 2 and n == 0 then
      -- Un completo vacío diría que se ha vendido todo: mejor no guardarlo.
      Cancel("el servidor no ha mandado ninguna subasta; no guardo el escaneo completo.")
    elseif stable >= 2 then
      ProcessReplicate(n)
    else
      C_Timer.After(0.5, check)
    end
  end
  check()
end

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

-- El precio mínimo por unidad de cada objeto en la última lista de resultados: RecordItem lo usa
-- para saber cómo vienen los precios de las subastas sueltas.
local browseMin = {}

-- Lista de resultados: el precio mínimo y la cantidad de cada objeto.
local function RecordBrowse()
  if Scan.state == "browse" then return end
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
    browseMin[itemID] = a.min
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
-- Ojo: en Forever una fila puede juntar varias subastas iguales («702 a 1 p»): quantity es cuántas
-- hay y buyoutAmount lo que cuesta cada una, no la fila entera. Si fuera un montón, buyoutAmount sería
-- el del montón. Como las filas no lo dicen, manda el mínimo por unidad de la lista de resultados:
-- se toma la lectura cuyo mínimo se le acerca más. Sin esa lista y con filas de más de uno, no se
-- apunta nada (mejor sin precio que con uno 700 veces más bajo).
local function RecordItem(itemKey)
  local AH = C_AuctionHouse
  local itemID = type(itemKey) == "table" and itemKey.itemID
  if not (itemID and AH.GetNumItemSearchResults and AH.GetItemSearchResultInfo) then return end
  local rows, several = {}, false
  local minEach, minSplit
  for i = 1, AH.GetNumItemSearchResults(itemKey) or 0 do
    local r = AH.GetItemSearchResultInfo(itemKey, i)
    local count = r and r.quantity or 0
    if r and r.buyoutAmount and r.buyoutAmount > 0 and count > 0 then
      rows[#rows + 1] = { price = r.buyoutAmount, count = count }
      several = several or count > 1
      local split = math.floor(r.buyoutAmount / count)
      if not minEach or r.buyoutAmount < minEach then minEach = r.buyoutAmount end
      if not minSplit or split < minSplit then minSplit = split end
    end
  end
  if #rows == 0 then return end
  local perAuction = true  -- buyoutAmount es lo que cuesta cada unidad de la fila
  if several then
    local anchor = browseMin[itemID]
    if not anchor then return end
    perAuction = math.abs(minEach - anchor) <= math.abs(minSplit - anchor)
  end
  local book, min, qty = {}, nil, 0
  for _, row in ipairs(rows) do
    local unit = perAuction and row.price or math.floor(row.price / row.count)
    book[unit] = (book[unit] or 0) + row.count
    qty = qty + row.count
    if not min or unit < min then min = unit end
  end
  NoteSearch(itemID, BookText(book, min, qty, #rows), true)
end

ns.On("COMMODITY_SEARCH_RESULTS_UPDATED", function(_, itemID)
  if Scan.state == "browse" or not itemID then return end
  ns.Debounce("ahcommodity" .. itemID, 0.3, function() RecordCommodity(itemID) end)
end)
local lastItemKey -- el último objeto suelto abierto: el que compras con PlaceBid

ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(_, itemKey)
  if Scan.state == "browse" or type(itemKey) ~= "table" or not itemKey.itemID then return end
  lastItemKey = itemKey
  ns.Debounce("ahitem" .. itemKey.itemID, 0.3, function() RecordItem(itemKey) end)
end)

-- Lo que compras --------------------------------------------------------------------------
-- Al comprar se acaban las subastas más baratas y el precio sube. Se apunta en el momento: lo
-- comprado se quita de la lista de precios que ya tenemos (las más baratas primero) y se vuelve
-- a pedir al servidor la lista de ese objeto, que la deja exacta. El tooltip, la ventana de
-- profesión y las pestañas Cajones y Libranzas lo ven al instante, y el motor lo lee como el resto de búsquedas.

-- Quita qty unidades, de la más barata a la más cara, de la lista entera del objeto.
local function DeductBought(itemID, qty)
  local text = search and searchExact[itemID] and search.items[itemID]
  if type(text) ~= "string" or not qty or qty <= 0 then return end
  local head, levels = text:match("^([^|]*)|(.*)$")
  local n = head and tonumber(head:match("^[^,]*,[^,]*,(%d+)"))
  if not levels then return end
  local book, min, total, left = {}, nil, 0, qty
  for price, count in levels:gmatch("(%d+):(%d+)") do
    price, count = tonumber(price), tonumber(count)
    local take = math.min(count, left)
    left = left - take
    count = count - take
    if count > 0 then
      book[price] = (book[price] or 0) + count
      total = total + count
      if not min or price < min then min = price end
    end
  end
  -- Si te lo has llevado todo no sabemos el precio siguiente: lo dirá la lista nueva.
  if not min then return end
  NoteSearch(itemID, BookText(book, min, total, math.max(1, n or 1)), true)
end

-- Pide otra vez al servidor la lista de un objeto (llega por *_SEARCH_RESULTS_UPDATED).
local function Requery(itemKey)
  local AH = C_AuctionHouse
  if not (ns.ahOpen and itemKey and AH.SendSearchQuery) then return end
  local sorts = { { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false } }
  SendWhenReady(function()
    if ns.ahOpen and Scan.state ~= "browse" then pcall(AH.SendSearchQuery, itemKey, sorts, false) end
  end)
end

local function KeyFor(itemID)
  local AH = C_AuctionHouse
  return AH.MakeItemKey and AH.MakeItemKey(itemID) or { itemID = itemID }
end

local buying -- la compra de un material que se está confirmando: { itemID, qty }

local function Guard(name, fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok then ns.ReportError(name, err) end
  end
end

if C_AuctionHouse and C_AuctionHouse.ConfirmCommoditiesPurchase then
  hooksecurefunc(C_AuctionHouse, "ConfirmCommoditiesPurchase", Guard("precio tras comprar", function(itemID, quantity)
    buying = { itemID = itemID, qty = quantity }
  end))
end

ns.On("COMMODITY_PURCHASE_SUCCEEDED", Guard("precio tras comprar", function()
  local b = buying
  buying = nil
  if not (b and b.itemID) then return end
  DeductBought(b.itemID, b.qty)
  Requery(KeyFor(b.itemID))
end))
ns.On("COMMODITY_PURCHASE_FAILED", function() buying = nil end)

-- Objetos sueltos: al comprar uno, la lista se vuelve a pedir en cuanto el servidor lo ha quitado.
if C_AuctionHouse and C_AuctionHouse.PlaceBid then
  hooksecurefunc(C_AuctionHouse, "PlaceBid", Guard("precio tras comprar", function()
    local key = lastItemKey
    if key then C_Timer.After(1.5, function() Requery(key) end) end
  end))
end

local function OnBrowseEvent()
  if Scan.state == "browse" then
    ns.Debounce("ahbrowse", 0.3, AdvanceBrowse)
  elseif ns.ahOpen then  -- tus búsquedas, también con el escaneo completo en marcha
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

local function AutoScanDue()
  return PitiGoldsDB.autoScan ~= false and time() - (PitiGoldsDB.lastFull or 0) >= AUTO_EVERY
end

local function OnAuctionHouseOpened()
  if ns.ahOpen then return end
  ns.ahOpen = true
  if ns.ShowAuctionButtons then ns.ShowAuctionButtons() end
  C_Timer.After(AUTO_DELAY, function()
    if ns.ahOpen and Scan.state == "idle" and AutoScanDue() then Scan.StartFull(true) end
  end)
  C_Timer.After(1, function()
    if ns.ahOpen and Scan.state ~= "browse" and C_AuctionHouse.QueryOwnedAuctions then
      pcall(C_AuctionHouse.QueryOwnedAuctions, {})
    end
  end)
end

local function OnAuctionHouseClosed()
  if not ns.ahOpen then return end
  ns.ahOpen = false
  search, searchExact = nil, {}  -- la próxima visita empieza otro escaneo de búsquedas
  Cancel(Scan.state ~= "idle" and "escaneo cancelado al cerrar la subasta; el completo se guarda solo al volver." or nil)
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

ns.Command("completo", "escaneo completo de la subasta", function() Scan.StartFull() end)
ns.Command("materiales", "escaneo de materiales y consumibles", function() Scan.StartMaterials() end)
ns.Command("auto", "enciende o apaga el escaneo completo automático al abrir la subasta", function()
  PitiGoldsDB.autoScan = PitiGoldsDB.autoScan == false
  ns.Print(PitiGoldsDB.autoScan and "escaneo automático encendido: al abrir la subasta, como mucho cada 15 minutos."
    or "escaneo automático apagado. Vuelve a encenderlo con /pg auto.")
end)
