-- Entorno falso de WoW para probar el addon fuera del juego (Lua 5.1, como WoW).
-- Imita solo las partes de la API que usa PitiGolds y simula las respuestas del
-- servidor con temporizadores, igual que llegarían los eventos en el juego.

Mock = {
  startNow = 1762300000,
  startGame = 1000,
  gameTime = 1000,
  timers = {},
  timerSeq = 0,
  frames = {},
  chat = {},
  reloaded = false,
  unknownEvents = {},
}

function time() return math.floor(Mock.startNow + (Mock.gameTime - Mock.startGame)) end
function GetTime() return Mock.gameTime end
date = os.date

-- Temporizadores -------------------------------------------------------------------

function Mock.Schedule(delay, fn)
  Mock.timerSeq = Mock.timerSeq + 1
  table.insert(Mock.timers, { at = Mock.gameTime + delay, seq = Mock.timerSeq, fn = fn })
end

C_Timer = { After = function(delay, fn) Mock.Schedule(delay, fn) end }

-- Avanza el reloj ejecutando por orden los temporizadores que vencen.
function Mock.Advance(seconds)
  local target = Mock.gameTime + seconds
  while true do
    local best, bestIndex
    for i, t in ipairs(Mock.timers) do
      if t.at <= target and (not best or t.at < best.at or (t.at == best.at and t.seq < best.seq)) then
        best, bestIndex = t, i
      end
    end
    if not best then break end
    table.remove(Mock.timers, bestIndex)
    if best.at > Mock.gameTime then Mock.gameTime = best.at end
    best.fn()
  end
  Mock.gameTime = target
end

-- Frames ------------------------------------------------------------------------------

local Frame = {}
local FrameMeta = {
  __index = function(_, key)
    return Frame[key] or function() end -- métodos de dibujo que no importan aquí
  end,
}

function Frame:RegisterEvent(event)
  if Mock.unknownEvents[event] then error("Attempt to register unknown event " .. event) end
  self.events[event] = true
end
function Frame:UnregisterEvent(event) self.events[event] = nil end
function Frame:SetScript(name, fn) self.scripts[name] = fn end
function Frame:GetScript(name) return self.scripts[name] end
function Frame:Show() self.shown = true end
function Frame:Hide() self.shown = false end
function Frame:IsShown() return self.shown end
function Frame:SetText(text) self.text = text end
function Frame:GetText() return self.text end
function Frame:SetPoint(...) self.point = { ... } end
function Frame:GetPoint() return unpack(self.point or { "CENTER", nil, "CENTER", 0, 0 }) end
function Frame:CreateFontString() return Mock.NewFrame() end
function Frame:CreateTexture()
  local t = Mock.NewFrame()
  t.parent = self
  return t
end
function Frame:SetTexture(path)
  self.texture = path
  -- Para las pruebas: la calavera que el addon pone sobre las placas.
  if path == "Interface\\TargetingFrame\\UI-RaidTargetingIcon_8" then self.marksPlate = true end
end
function Frame:SetRotation(angle) self.rotation = angle end

function Mock.NewFrame(name)
  local f = setmetatable({ events = {}, scripts = {}, shown = true, name = name }, FrameMeta)
  table.insert(Mock.frames, f)
  if name then _G[name] = f end
  return f
end

function CreateFrame(_, name, parent)
  local f = Mock.NewFrame(name)
  f.parentFrame = parent
  return f
end

UIParent = Mock.NewFrame("UIParent")
DEFAULT_CHAT_FRAME = { AddMessage = function(_, msg) table.insert(Mock.chat, msg) end }
SlashCmdList = {}

function Mock.Fire(event, ...)
  for _, f in ipairs(Mock.frames) do
    if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
  end
end

function Mock.Slash(text)
  SlashCmdList.PITIGOLDS(text)
end

function Mock.ClickButton(label)
  for _, f in ipairs(Mock.frames) do
    if f.text == label and f.scripts.OnClick then
      f.scripts.OnClick(f)
      return true
    end
  end
  return false
end

-- hooksecurefunc("Nombre", fn) o hooksecurefunc(tabla, "Nombre", fn), como en WoW.
function hooksecurefunc(a, b, c)
  local owner, name, hook = _G, a, b
  if type(a) == "table" then owner, name, hook = a, b, c end
  local original = owner[name]
  owner[name] = function(...)
    local results = { original(...) }
    hook(...)
    return unpack(results)
  end
end

function InCombatLockdown() return false end

function ReloadUI() Mock.reloaded = true end

-- Personaje -----------------------------------------------------------------------------

Mock.player = { name = "Brujo", realm = "Dio", money = 1234567 }

function GetBuildInfo() return "1.60.1", "70532", "Oct 28 2026", 16001 end
-- Otras unidades (target, mouseover, nameplate1...): Mock.units[unidad] = { name, guid, dead }
Mock.units = {}
function UnitName(unit)
  if unit == "npc" then return Mock.merchant.npc end
  if Mock.units[unit] then return Mock.units[unit].name end
  return Mock.player.name
end
function UnitIsDead(unit) return Mock.units[unit] ~= nil and Mock.units[unit].dead == true end
function GetCVar(name) return Mock.cvars and Mock.cvars[name] end
function GetRealmName() return Mock.player.realm end
function GetNormalizedRealmName() return (Mock.player.realm:gsub("%s", "")) end
function UnitFactionGroup() return "Horde" end
function UnitClass() return "Brujo", "WARLOCK" end
function UnitRace() return "Orco", "Orc" end
function UnitLevel() return 60 end
function UnitGUID(unit)
  if Mock.units[unit] then return Mock.units[unit].guid end
  if unit == "player" then return "Player-1-00000001" end
end
function GetMoney() return Mock.player.money end

-- Instructor: Mock.trainer.services = { { name, kind, skill, rank, level, cost }, ... }. Como en el
-- juego, la lista solo enseña los tipos que dejan pasar los filtros de la ventana.
Mock.trainer = { services = {}, filters = { available = true, unavailable = false, used = false } }
local function TrainerServices()
  local list = {}
  for _, s in ipairs(Mock.trainer.services) do
    if s.kind == "header" or Mock.trainer.filters[s.kind] then list[#list + 1] = s end
  end
  return list
end
function GetNumTrainerServices() return #TrainerServices() end
function GetTrainerServiceInfo(i)
  local s = TrainerServices()[i]
  if s then return s.name, "", s.kind, true end
end
function GetTrainerServiceSkillReq(i)
  local s = TrainerServices()[i]
  if s and s.skill then return s.skill, s.rank, true end
end
function GetTrainerServiceLevelReq(i) return (TrainerServices()[i] or {}).level end
function GetTrainerServiceCost(i) return (TrainerServices()[i] or {}).cost end
function GetTrainerServiceTypeFilter(kind) return Mock.trainer.filters[kind] end
function SetTrainerServiceTypeFilter(kind, on) Mock.trainer.filters[kind] = on == 1 end

Enum = {
  BagIndex = {
    Backpack = 0, Bag_1 = 1, Bag_2 = 2, Bag_3 = 3, Bag_4 = 4, ReagentBag = 5,
    Bank = -1, Reagentbank = -3,
    BankBag_1 = 6, BankBag_2 = 7, BankBag_3 = 8, BankBag_4 = 9, BankBag_5 = 10, BankBag_6 = 11, BankBag_7 = 12,
    AccountBankTab_1 = 13, AccountBankTab_2 = 14, AccountBankTab_3 = 15, AccountBankTab_4 = 16, AccountBankTab_5 = 17,
  },
  PlayerInteractionType = { Merchant = 5, Banker = 8, MailInfo = 17, Auctioneer = 21, AccountBanker = 68 },
  TooltipDataType = { Item = 0 },
  TooltipDataLineType = { SellPrice = 11 },
  ItemClass = { Consumable = 0, Reagent = 5, Tradegoods = 7, Gem = 3, ItemEnhancement = 8, Recipe = 9, Profession = 19 },
  AuctionHouseSortOrder = { Price = 0, Name = 1 },
  BankType = { Character = 0, Guild = 1, Account = 2 },
}
NUM_TOTAL_EQUIPPED_BAG_SLOTS = 5
ATTACHMENTS_MAX_RECEIVE = 16
ATTACHMENTS_MAX_SEND = 12

Mock.mapID = 1411
Mock.mapNames = { [1411] = "Durotar", [1413] = "Los Baldíos" }
-- Posición: cada mapa ocupa 1000 x 1000 metros del continente 1, con su esquina noroeste en
-- Mock.mapCorners[mapa] = { norte, oeste }. Mock.position = { norte, oeste }.
Mock.mapCorners = { [1411] = { 1000, 5000 }, [1413] = { 0, 5000 } }
Mock.position = { 500, 4500 }
Mock.facing = 0
C_Map = {
  GetBestMapForUnit = function() return Mock.mapID end,
  GetMapInfo = function(id) return { name = Mock.mapNames[id] or "?" } end,
  GetWorldPosFromMapPos = function(id, pos)
    local corner = Mock.mapCorners[id]
    if not corner then return nil end
    local north, west = corner[1] - pos.y * 1000, corner[2] - pos.x * 1000
    return 1, { GetXY = function() return north, west end }
  end,
}
C_Map.GetPlayerMapPosition = function(id)
  local corner = Mock.mapCorners[id]
  if not corner then return nil end
  local x, y = (corner[2] - Mock.position[2]) / 1000, (corner[1] - Mock.position[1]) / 1000
  return { GetXY = function() return x, y end }
end
-- Los dos mapas de las pruebas están uno encima del otro en el mapa 1414 (el continente), que mide
-- 1000 x 2000 metros: Durotar arriba y Los Baldíos abajo.
Mock.mapRects = { [1411] = { 0, 1, 0, 0.5 }, [1413] = { 0, 1, 0.5, 1 } }
C_Map.GetMapRectOnMap = function(id, top)
  local r = top == 1414 and Mock.mapRects[id]
  if r then return r[1], r[2], r[3], r[4] end
end
function CreateVector2D(x, y) return { x = x, y = y } end

-- Mapa del mundo: un lienzo de 1000 x 1000 con el mapa que se está viendo.
function Mock.NewWorldMap()
  local canvas = Mock.NewFrame()
  function canvas:GetWidth() return 1000 end
  function canvas:GetHeight() return 1000 end
  function canvas:HookScript(name, fn) self.hooks = self.hooks or {}; self.hooks[name] = fn end
  function canvas:GetFrameLevel() return 1 end
  local map = Mock.NewFrame("WorldMapFrame")
  map.ScrollContainer = { Child = canvas }
  map.mapID = 1413
  map.shown = false
  function map:GetMapID() return self.mapID end
  function map:OnMapChanged() end
  function map:HookScript(name, fn) self.hooks = self.hooks or {}; self.hooks[name] = fn end
  return map
end

-- Las marcas que hay pintadas en el mapa del mundo: { { texture, x, y }, ... }.
function Mock.MapPins()
  local canvas = WorldMapFrame and WorldMapFrame.ScrollContainer.Child
  local list = {}
  for _, f in ipairs(Mock.frames) do
    local parent = rawget(f, "parent")
    if f.shown and parent and rawget(parent, "parentFrame") == canvas and rawget(f, "point") then
      list[#list + 1] = { texture = f.texture, x = f.point[4], y = f.point[5] }
    end
  end
  return list
end
function UnitPosition() return Mock.position[1], Mock.position[2], 0, 1 end
function GetPlayerFacing() return Mock.facing end
function GetZoneText() return Mock.mapNames[Mock.mapID] end

-- Simula que entra algo en las bolsas (o que cambia el oro) y avisa como el juego.
function Mock.Loot(bag, slot, itemID, count)
  Mock.bags[bag] = Mock.bags[bag] or { numSlots = 16 }
  local current = Mock.bags[bag][slot]
  if current and current.itemID == itemID then
    current.stackCount = current.stackCount + count
  else
    Mock.bags[bag][slot] = { itemID = itemID, stackCount = count, hyperlink = "[" .. (Mock.itemNames[itemID] or "?") .. "]" }
  end
  Mock.Fire("BAG_UPDATE_DELAYED")
end
function Mock.AddMoney(copper)
  Mock.player.money = Mock.player.money + copper
  Mock.Fire("PLAYER_MONEY")
end

Mock.itemNames = {}
Mock.sellPrices = {}
Mock.stackSizes = {}
local function CountItem(itemID, bags)
  local n = 0
  for _, bag in ipairs(bags) do
    for slot, info in pairs(Mock.bags[bag] or {}) do
      if type(slot) == "number" and info.itemID == itemID then n = n + info.stackCount end
    end
  end
  return n
end

C_Item = {
  GetItemCount = function(itemID, includeBank)
    local n = CountItem(itemID, { 0, 1, 2, 3, 4, 5 })
    if includeBank then n = n + CountItem(itemID, { -1, 6, 7, 8, 9, 10, 11, 12 }) end
    return n
  end,
  GetItemNameByID = function(id) return Mock.itemNames[id] end,
  GetItemMaxStackSizeByID = function(id) return Mock.stackSizes[id] end,
  GetItemID = function(location) return location.itemID end,
  -- Solo importan el nombre (1.º valor) y el precio de venta al vendedor (11.º).
  GetItemInfo = function(id)
    local name = Mock.itemNames[id]
    if name then return name, nil, nil, nil, nil, nil, nil, nil, nil, nil, Mock.sellPrices[id] or 0 end
  end,
}

-- Vendedor: Mock.merchant.items = { { itemID, name, price, stack, numAvailable, costs } }
Mock.merchant = { npc = "Grimtak", items = {} }
function GetMerchantNumItems() return #Mock.merchant.items end
function GetMerchantItemID(i) return Mock.merchant.items[i].itemID end
function GetMerchantItemInfo(i)
  local it = Mock.merchant.items[i]
  return it.name, 0, it.price, it.stack or 1, it.numAvailable or -1, true, true, it.costs ~= nil
end
function GetMerchantItemCostInfo(i)
  local costs = Mock.merchant.items[i].costs
  return costs and #costs or 0
end
function GetMerchantItemCostItem(i, j)
  local c = Mock.merchant.items[i].costs[j]
  return 0, c.value, c.link, c.currencyName
end

-- Tooltips: Mock.Tooltip(itemID, count, sellTotal) devuelve las líneas del tooltip:
-- la de «Precio de venta» del juego (si nadie la quita) y las que añade el addon.
Mock.tooltipCallbacks = {}
Mock.tooltipLineCallbacks = {}
TooltipDataProcessor = {
  AddTooltipPostCall = function(_, fn) table.insert(Mock.tooltipCallbacks, fn) end,
  AddLinePreCall = function(lineType, fn)
    Mock.tooltipLineCallbacks[lineType] = Mock.tooltipLineCallbacks[lineType] or {}
    table.insert(Mock.tooltipLineCallbacks[lineType], fn)
  end,
}
-- Con skipPostCalls, el cliente no llama a los post-calls si alguien quita una línea.
Mock.tooltipFrames = {}
function Mock.Tooltip(itemID, count, sellTotal, skipPostCalls)
  local lines = {}
  local owner = { count = count }
  local tooltip = Mock.tooltipFrames[1] or {}
  Mock.tooltipFrames[1] = tooltip
  if tooltip.onCleared then tooltip.onCleared(tooltip) end
  tooltip.processingInfo = { tooltipData = { id = itemID } }
  tooltip.HookScript = function(self, script, fn) if script == "OnTooltipCleared" then self.onCleared = fn end end
  for k, v in pairs({
    GetOwner = function() return owner end,
    AddLine = function(_, text) lines[#lines + 1] = text end,
    AddDoubleLine = function(_, left, right, lr, lg, lb)
      local color = (lr == 0.25 and lg == 1) and "[verde] " or ""
      lines[#lines + 1] = color .. left .. " = " .. right
    end,
  }) do tooltip[k] = v end
  local hidden = false
  if sellTotal then
    for _, fn in ipairs(Mock.tooltipLineCallbacks[Enum.TooltipDataLineType.SellPrice] or {}) do
      if fn(tooltip, { price = sellTotal }) then hidden = true break end
    end
    if not hidden then lines[#lines + 1] = "Precio de venta: " .. sellTotal end
  end
  if not (hidden and skipPostCalls) then
    for _, fn in ipairs(Mock.tooltipCallbacks) do fn(tooltip, { id = itemID }) end
  end
  return table.concat(lines, "\n")
end

-- Macros: Mock.macros[i] = { name, icon, body }
Mock.macros = {}
function GetMacroIndexByName(name)
  for i, m in ipairs(Mock.macros) do
    if m.name == name then return i end
  end
  return 0
end
function CreateMacro(name, icon, body)
  table.insert(Mock.macros, { name = name, icon = icon, body = body })
  return #Mock.macros
end
function EditMacro(index, name, icon, body)
  local m = Mock.macros[index]
  m.name, m.icon, m.body = name or m.name, icon or m.icon, body or m.body
  return index
end

-- Placas de nombre: Mock.AddPlate("nameplate1", { name, guid }) avisa como el juego.
Mock.plates = {}
C_NamePlate = {
  GetNamePlateForUnit = function(unit) return Mock.plates[unit] end,
  GetNamePlates = function()
    local list = {}
    for _, plate in pairs(Mock.plates) do list[#list + 1] = plate end
    return list
  end,
}
function Mock.AddPlate(unit, info)
  Mock.units[unit] = info
  Mock.plates[unit] = Mock.NewFrame()
  Mock.plates[unit].namePlateUnitToken = unit
  Mock.Fire("NAME_PLATE_UNIT_ADDED", unit)
end
function Mock.RemovePlate(unit)
  Mock.Fire("NAME_PLATE_UNIT_REMOVED", unit)
  Mock.plates[unit] = nil
  Mock.units[unit] = nil
end
-- Cuántas calaveras se ven ahora sobre las placas.
function Mock.MarkedPlates()
  local n = 0
  for _, f in ipairs(Mock.frames) do
    local parent = rawget(f, "parent")
    local onMap = parent and WorldMapFrame and rawget(parent, "parentFrame") == WorldMapFrame.ScrollContainer.Child
    if rawget(f, "marksPlate") and parent and parent.shown and not onMap then n = n + 1 end
  end
  return n
end

-- Botín abierto: Mock.loot[i] = { itemID, sources = { guid, cantidad, ... } }
Mock.loot = {}
function GetNumLootItems() return #Mock.loot end
function GetLootSlotLink(slot)
  local it = Mock.loot[slot]
  return it and ("|cffffffff|Hitem:" .. it.itemID .. "::::::::60:::::|h[x]|h|r")
end
function GetLootSourceInfo(slot) return unpack(Mock.loot[slot].sources) end

-- Bolsas: Mock.bags[bag] = { numSlots = n, [slot] = { itemID, stackCount, hyperlink, isBound } }
Mock.bags = {}
C_Container = {
  GetContainerNumSlots = function(bag) return Mock.bags[bag] and Mock.bags[bag].numSlots or 0 end,
  GetContainerItemInfo = function(bag, slot) return Mock.bags[bag] and Mock.bags[bag][slot] end,
}
Mock.warbandMoney = 0
C_Bank = { FetchDepositedMoney = function() return Mock.warbandMoney end }

Mock.currencies = {}
C_CurrencyInfo = { GetCurrencyInfo = function(id) return Mock.currencies[id] end }

Mock.factions = {}
C_Reputation = {
  GetNumFactions = function() return #Mock.factions end,
  GetFactionDataByIndex = function(i) return Mock.factions[i] end,
}

Mock.professions = {}
function GetProfessions() return 1, 2, nil, nil, 5 end
function GetProfessionInfo(index)
  local p = Mock.professions[index]
  if p then return p.name, 0, p.rank, p.maxRank, 0, 0, p.skillLine, 0 end
end

-- Profesión abierta -------------------------------------------------------------------------

Mock.tradeSkill = { recipes = {}, schematics = {}, sources = {} }
C_TradeSkillUI = {
  IsTradeSkillReady = function() return true end,
  IsTradeSkillLinked = function() return false end,
  IsTradeSkillGuild = function() return false end,
  IsNPCCrafting = function() return false end,
  GetBaseProfessionInfo = function() return Mock.tradeSkill.base end,
  GetChildProfessionInfo = function() return Mock.tradeSkill.child end,
  GetAllRecipeIDs = function()
    local ids = {}
    for id in pairs(Mock.tradeSkill.recipes) do ids[#ids + 1] = id end
    table.sort(ids)
    return ids
  end,
  GetRecipeInfo = function(id) return Mock.tradeSkill.recipes[id] end,
  GetRecipeSchematic = function(id) return Mock.tradeSkill.schematics[id] end,
  GetRecipeSourceText = function(id) return Mock.tradeSkill.sources[id] end,
  GetCategoryInfo = function(id) return { name = "Categoría " .. id, parentCategoryID = 0 } end,
}

-- Correo --------------------------------------------------------------------------------------

Mock.inbox = {}
Mock.sendItems = {}
function GetInboxNumItems() return #Mock.inbox, #Mock.inbox end
function GetInboxHeaderInfo(i)
  local m = Mock.inbox[i]
  return nil, nil, m.sender, m.subject, m.money or 0, m.cod or 0, m.daysLeft or 30, #(m.items or {})
end
function GetInboxItem(i, j)
  local it = Mock.inbox[i].items and Mock.inbox[i].items[j]
  if it then return it.name, it.itemID, 0, it.count end
end
function SendMail() end
-- Facturas de la subasta: Mock.inbox[i].invoice = { type, itemName, bid, deposit, cut, count }
function GetInboxInvoiceInfo(i)
  local inv = Mock.inbox[i] and Mock.inbox[i].invoice
  if inv then
    return inv.type, inv.itemName, "Comprador", inv.bid, inv.bid, inv.deposit, inv.cut, 0, 0, inv.count
  end
end
function TakeInboxMoney() end
function AutoLootMailItem() end
function TakeInboxItem() end
function GetSendMailItem(i)
  local it = Mock.sendItems[i]
  if it then return it.name, it.itemID, 0, it.count end
end
function GetSendMailMoney() return 0 end

-- Casa de subastas ------------------------------------------------------------------------------
-- Mock.replicate: lista de subastas { itemID, count, buyout, owner, name }
-- Mock.browseData[classID]: lista de resultados de búsqueda, se sirven en páginas de 2.

Mock.replicate = {}
Mock.browseData = {}
Mock.owned = {}
Mock.browseQueries = 0
Mock.itemKeySearches = {}

local browse = { results = {}, all = {} }

C_AuctionHouse = {
  ReplicateItems = function()
    Mock.Schedule(3, function() Mock.Fire("REPLICATE_ITEM_LIST_UPDATE") end)
  end,
  GetNumReplicateItems = function() return #Mock.replicate end,
  GetReplicateItemInfo = function(index)
    local a = Mock.replicate[index + 1]
    return a.name, 0, a.count, 1, true, 1, 0, 0, 0, a.buyout, 0, false, nil, a.owner, a.owner, 0, a.itemID, true
  end,
  IsThrottledMessageSystemReady = function() return true end,
  SendBrowseQuery = function(query)
    Mock.browseQueries = Mock.browseQueries + 1
    browse.all = Mock.browseData[query.itemClassFilters[1].classID] or {}
    browse.results = {}
    for i = 1, math.min(2, #browse.all) do browse.results[i] = browse.all[i] end
    Mock.Schedule(0.5, function() Mock.Fire("AUCTION_HOUSE_BROWSE_RESULTS_UPDATED") end)
  end,
  RequestMoreBrowseResults = function()
    local n = #browse.results
    for i = n + 1, math.min(n + 2, #browse.all) do browse.results[i] = browse.all[i] end
    Mock.Schedule(0.5, function() Mock.Fire("AUCTION_HOUSE_BROWSE_RESULTS_ADDED", {}) end)
  end,
  GetBrowseResults = function() return browse.results end,
  MakeItemKey = function(itemID) return { itemID = itemID, itemLevel = 0, itemSuffix = 0, battlePetSpeciesID = 0 } end,
  -- Búsquedas por objetos (botón Buscar de la ventana de profesión): se apuntan en Mock.itemKeySearches.
  SearchForItemKeys = function(keys, sorts)
    local ids = {}
    for i, k in ipairs(keys) do ids[i] = k.itemID end
    table.insert(Mock.itemKeySearches, ids)
  end,
  HasFullBrowseResults = function() return #browse.results >= #browse.all end,
  QueryOwnedAuctions = function()
    Mock.Schedule(0.5, function() Mock.Fire("OWNED_AUCTIONS_UPDATED") end)
  end,
  GetNumOwnedAuctions = function() return #Mock.owned end,
  GetOwnedAuctionInfo = function(i) return Mock.owned[i] end,
  -- Compra de materiales: primero el presupuesto y, al confirmar, la compra.
  StartCommoditiesPurchase = function(itemID, quantity)
    local unit = Mock.commodityPrices[itemID] or 0
    Mock.Schedule(0.2, function() Mock.Fire("COMMODITY_PRICE_UPDATED", unit, unit * quantity) end)
  end,
  ConfirmCommoditiesPurchase = function(itemID, quantity)
    Mock.Schedule(0.5, function()
      Mock.player.money = Mock.player.money - (Mock.commodityPrices[itemID] or 0) * quantity
      Mock.Fire("COMMODITY_PURCHASE_SUCCEEDED")
    end)
  end,
  PostCommodity = function() end,
  PostItem = function() end,
  CalculateCommodityDeposit = function(_, _, quantity) return 10 * quantity end,
  CalculateItemDeposit = function(_, _, quantity) return 50 * quantity end,
}
Mock.commodityPrices = {}

-- Carga del addon y guardado -------------------------------------------------------------------

-- En las pruebas el dinero sale en texto («1p 75c») en vez de con los iconos del juego.
Mock.ns = { coinIcons = { gold = "o", silver = "p", copper = "c" } }

function Mock.LoadAddon(dir, files)
  for _, file in ipairs(files) do
    local chunk, err = loadfile(dir .. "/" .. file)
    if chunk then
      chunk("PitiGolds", Mock.ns)
    elseif file ~= "Generated.lua" then
      -- Generated.lua no existe hasta que el motor lo escribe; el addon funciona sin él.
      error(err)
    end
  end
end

-- Escribe una variable como lo hace WoW en SavedVariables.
function Mock.Serialize(name, value)
  local out = {}
  local function write(v, indent)
    local t = type(v)
    if t == "table" then
      out[#out + 1] = "{\n"
      local n = #v
      for i = 1, n do
        out[#out + 1] = indent .. "\t"
        write(v[i], indent .. "\t")
        out[#out + 1] = ", -- [" .. i .. "]\n"
      end
      for k, val in pairs(v) do
        local isArray = type(k) == "number" and k >= 1 and k <= n and k == math.floor(k)
        if not isArray then
          out[#out + 1] = indent .. "\t["
          out[#out + 1] = type(k) == "string" and string.format("%q", k) or string.format("%.0f", k)
          out[#out + 1] = "] = "
          write(val, indent .. "\t")
          out[#out + 1] = ",\n"
        end
      end
      out[#out + 1] = indent .. "}"
    elseif t == "string" then
      out[#out + 1] = string.format("%q", v)
    elseif t == "number" then
      out[#out + 1] = (v == math.floor(v)) and string.format("%.0f", v) or tostring(v)
    elseif t == "boolean" then
      out[#out + 1] = tostring(v)
    else
      out[#out + 1] = "nil"
    end
  end
  out[#out + 1] = name .. " = "
  write(value, "")
  out[#out + 1] = "\n"
  return table.concat(out)
end
