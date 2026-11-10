-- En la ventana de profesión, debajo de los materiales de la receta elegida: cuánto cuesta
-- fabricarla (materiales al mejor precio, de subasta o de vendedor) y cuánto se gana vendiendo
-- lo fabricado, ya sin la comisión de la subasta. Las cuentas las hace el motor (recipes en
-- Generated.lua), con los mismos precios que el informe. Al lado, el botón Buscar busca en la
-- subasta los materiales de la receta (si está cerrada, al abrirla).
local ADDON, ns = ...

local AH_CUT = 0.05

-- La receta con lo último visto en la subasta (tus búsquedas o un escaneo que el motor aún no ha
-- leído). Parte del desglose del motor (recipeParts): "objeto,unidades,valor,venta,depósito|
-- material:cantidad:coste:tienda;...". Devuelve coste y ganancia, o nil si no hay nada más nuevo.
local function LiveCraft(detail)
  if type(detail) ~= "string" or not ns.ScanMarket then return nil end
  local head, parts = detail:match("^([^|]*)|(.*)$")
  if not head then return nil end
  local out, outQty, value, vendorSell, deposit = head:match("^(%d*),([%d%.]*),(%-?%d*),(%d*),([%d%.]*)$")
  if not out then return nil end
  local used, cost = false, 0
  for item, qty, unit, shop in parts:gmatch("(%d+):(%d+):(%d*):(%d*)") do
    local price = tonumber(unit)
    local seen = ns.ScanMarket(tonumber(item))
    if seen then
      used = true
      local vendor = tonumber(shop)
      price = vendor and math.min(vendor, seen) or seen
    end
    if not price then return nil end
    cost = cost + price * tonumber(qty)
  end
  value = tonumber(value)
  local seenOut = tonumber(out) and ns.ScanMarket(tonumber(out))
  if seenOut then
    used = true
    local net = math.max(0, math.floor(seenOut * (1 - AH_CUT) - (tonumber(deposit) or 0) + 0.5))
    value = math.floor(math.max(net, tonumber(vendorSell) or 0) * (tonumber(outQty) or 1) + 0.5)
  end
  if not used then return nil end
  cost = math.floor(cost + 0.5)
  return cost, value and (value - cost)
end

-- Texto del recuadro para una receta, o nil si el motor no tiene su coste.
function ns.CraftInfoText(recipeID)
  local gen = PitiGoldsGenerated
  local data = recipeID and type(gen) == "table" and gen.recipes and gen.recipes[recipeID]
  if not data then return nil end
  local cost, profit = data:match("^(%d+),(%-?%d*)$")
  if not cost then return nil end
  local liveCost, liveProfit = LiveCraft(gen.recipeParts and gen.recipeParts[recipeID])
  if liveCost then cost, profit = liveCost, liveProfit end
  local text = "Fabricar: |cffffffff" .. ns.Money(cost) .. "|r"
  profit = tonumber(profit)
  if profit then
    text = text .. "\nGanancia: " .. (profit >= 0 and "|cff40ff40" or "|cffff4040") .. ns.Money(profit) .. "|r"
  end
  if liveCost then
    text = text .. "\n|cff999999con lo que acabas de ver en la subasta|r"
  end
  return text
end

-- Lista de la compra -----------------------------------------------------------------
-- Al pulsar Buscar se guarda lo que pide cada fabricación. En la subasta, al abrir uno de esos
-- materiales, se pone sola la cantidad que falta para fabricar ns.craftCount veces.

ns.craftCount = 1
local shopping        -- { need = { [itemID] = cantidad por fabricación }, names = { [itemID] = nombre } }
local commodityItemID -- el material abierto en la ventana de compra por unidades

local function Owned(itemID)
  local count = C_Item and C_Item.GetItemCount or GetItemCount
  if not count then return 0 end
  local ok, n = pcall(count, itemID, true, false, true)
  return ok and n or 0
end

-- Cuántos hay que comprar de un material de la lista, o nil si no está en ella.
function ns.ShoppingQuantity(itemID)
  local need = shopping and shopping.need[itemID]
  if not need then return nil end
  local owned = Owned(itemID)
  return math.max(0, need * ns.craftCount - owned), owned
end

-- Pone la cantidad en la ventana de compra de Blizzard. Prueba lo que exista en este cliente.
local function SetBuyQuantity(quantity)
  local frame = AuctionHouseFrame and AuctionHouseFrame.CommoditiesBuyFrame
  local display = frame and frame.BuyDisplay
  if not display then return false end
  if display.SetQuantitySelected then
    display:SetQuantitySelected(quantity)
    return true
  end
  local input = display.QuantityInput
  if not input then return false end
  if input.SetQuantity then
    input:SetQuantity(quantity)
  elseif input.InputBox then
    input.InputBox:SetText(tostring(quantity))
  else
    return false
  end
  local box = input.InputBox
  local callback = input.quantityChangedCallback or input.inputChangedCallback
    or (box and box.inputChangedCallback)
  if callback then
    callback()
  elseif box and box.GetScript and box:GetScript("OnTextChanged") then
    box:GetScript("OnTextChanged")(box, true)
  end
  return true
end

local function ApplyShopping(announce)
  local itemID = commodityItemID
  local quantity, owned = ns.ShoppingQuantity(itemID)
  if not quantity then return end
  local name = shopping.names[itemID] or ns.ItemNameByID(itemID) or ("objeto " .. itemID)
  if quantity <= 0 then
    if announce then
      ns.Print(("ya tienes %d %s: bastan para %d fabricaciones."):format(owned, name, ns.craftCount))
    end
    return
  end
  local ok, done = pcall(SetBuyQuantity, quantity)
  if announce or not (ok and done) then
    ns.Print(("%s: %s %d para %d fabricaciones%s."):format(name,
      (ok and done) and "marcados" or "compra", quantity, ns.craftCount,
      owned > 0 and (" (ya tienes " .. owned .. ")") or ""))
  end
end

-- El multiplicador de la barra de la subasta.
function ns.SetCraftCount(n)
  n = math.floor(tonumber(n) or 1)
  if n < 1 then n = 1 elseif n > 999 then n = 999 end
  local changed = n ~= ns.craftCount
  ns.craftCount = n
  if ns.UpdateCraftCountBox then ns.UpdateCraftCountBox() end
  if not changed then return end
  local frame = AuctionHouseFrame and AuctionHouseFrame.CommoditiesBuyFrame
  if commodityItemID and frame and frame.IsShown and frame:IsShown() then ApplyShopping(true) end
end

local hookedBuyFrame = false
local function HookBuyFrame()
  local frame = AuctionHouseFrame and AuctionHouseFrame.CommoditiesBuyFrame
  if hookedBuyFrame or not (frame and frame.SetItemIDAndPrice) then return end
  hookedBuyFrame = true
  hooksecurefunc(frame, "SetItemIDAndPrice", function(_, itemID)
    commodityItemID = itemID
    -- Después de que Blizzard ponga su cantidad por defecto.
    C_Timer.After(0, function()
      local ok, err = pcall(ApplyShopping, true)
      if not ok then ns.ReportError("cantidad a comprar", err) end
    end)
  end)
end
ns.On("AUCTION_HOUSE_SHOW", HookBuyFrame)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", HookBuyFrame)

-- Las fabricaciones que pone la ventana de profesión (el número junto a «Crear todo»).
local function ProfessionCraftCount()
  local page = ProfessionsFrame and ProfessionsFrame.CraftingPage
  local box = page and page.CreateMultipleInputBox
  if not (box and box.GetValue) then return nil end
  local ok, value = pcall(box.GetValue, box)
  value = ok and tonumber(value)
  return value and value > 1 and value or nil
end

-- Botón Buscar: busca en la subasta los materiales de la receta -------------------------

local BASIC_REAGENT = 1 -- Enum.CraftingReagentType.Basic
local pendingSearch    -- la búsqueda pedida con la subasta cerrada: se lanza al abrirla

-- Los materiales obligatorios de la receta: { name, items = { itemID... }, names = { ... } }.
local function ReagentSearch(recipeID)
  local T = C_TradeSkillUI
  if not (T and T.GetRecipeSchematic) then return nil end
  local ok, s = pcall(T.GetRecipeSchematic, recipeID, false)
  if not ok or type(s) ~= "table" then return nil end
  local search = { items = {}, names = {}, need = {}, nameOf = {} }
  for _, slot in ipairs(s.reagentSlotSchematics or {}) do
    if slot.required or slot.reagentType == BASIC_REAGENT then
      for _, r in ipairs(slot.reagents or {}) do
        if r.itemID and not search.need[r.itemID] then
          local name = ns.ItemNameByID(r.itemID) or ("objeto " .. r.itemID)
          search.need[r.itemID] = slot.quantityRequired or 1
          search.nameOf[r.itemID] = name
          search.items[#search.items + 1] = r.itemID
          search.names[#search.names + 1] = name
        end
      end
    end
  end
  if #search.items == 0 then return nil end
  return search
end

local function RunSearch(search)
  local AH = C_AuctionHouse
  if not AH then return end
  if ns.Scan and ns.Scan.state ~= "idle" then
    ns.Print("espera a que acabe el escaneo para buscar los materiales.")
    return
  end
  if AuctionHouseFrame and AuctionHouseFrame.SetDisplayMode and AuctionHouseFrameDisplayMode then
    pcall(AuctionHouseFrame.SetDisplayMode, AuctionHouseFrame, AuctionHouseFrameDisplayMode.Buy)
  end
  if AH.SearchForItemKeys then
    local keys = {}
    for i, itemID in ipairs(search.items) do
      keys[i] = AH.MakeItemKey and AH.MakeItemKey(itemID) or { itemID = itemID }
    end
    local sorts = {
      { sortOrder = Enum.AuctionHouseSortOrder.Price, reverseSort = false },
      { sortOrder = Enum.AuctionHouseSortOrder.Name, reverseSort = false },
    }
    ns.AuctionSendWhenReady(function() AH.SearchForItemKeys(keys, sorts) end)
  else
    -- Sin búsqueda por objetos: al menos el primer material, por su nombre.
    local bar = AuctionHouseFrame and AuctionHouseFrame.SearchBar
    if not (bar and bar.SearchBox and bar.StartSearch) then return end
    bar.SearchBox:SetText(search.names[1])
    bar:StartSearch()
  end
  ns.Print("buscando en la subasta: " .. table.concat(search.names, ", ") .. ".")
end

function ns.SearchRecipeReagents(recipeID)
  local search = recipeID and ReagentSearch(recipeID)
  if not search then
    ns.Print("esta receta no tiene materiales que buscar en la subasta.")
    return
  end
  shopping = { need = search.need, names = search.nameOf }
  local fromProfession = ProfessionCraftCount()
  if fromProfession then ns.SetCraftCount(fromProfession) end
  if ns.ahOpen then
    pendingSearch = nil
    RunSearch(search)
  else
    pendingSearch = search
    ns.Print("abre la subasta y buscaré " .. table.concat(search.names, ", ") .. ".")
  end
end

local function RunPending()
  local search = pendingSearch
  if not search or not ns.ahOpen then return end
  pendingSearch = nil
  -- Un momento para que la ventana de la subasta termine de montarse.
  C_Timer.After(0.5, function()
    if ns.ahOpen then RunSearch(search) end
  end)
end
ns.On("AUCTION_HOUSE_SHOW", RunPending)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", RunPending)

-- El recuadro --------------------------------------------------------------------------

local info, button, lastForm
local reported = false

-- Auctionator pone su propio «Fabricar/Ganancia» en el mismo sitio: el nuestro va debajo.
local function AuctionatorLoaded()
  local isLoaded = (C_AddOns and C_AddOns.IsAddOnLoaded) or IsAddOnLoaded
  if not isLoaded then return false end
  local ok, loaded = pcall(isLoaded, "Auctionator")
  return ok and loaded and true or false
end

local function Update(form)
  lastForm = form
  local recipe = form.GetRecipeInfo and form:GetRecipeInfo()
  local text = recipe and ns.CraftInfoText(recipe.recipeID)
  if not text then
    info:Hide()
    button:Hide()
    return
  end
  button.recipeID = recipe.recipeID
  button:Show()
  -- Debajo del último bloque de materiales que se vea.
  local anchor = type(form.Reagents) == "table" and form.Reagents or nil
  local optional = form.OptionalReagents
  if type(optional) == "table" and optional:IsShown() then anchor = optional end
  info:ClearAllPoints()
  if anchor then
    info:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, AuctionatorLoaded() and -48 or -10)
  else
    info:SetPoint("BOTTOMLEFT", form, "BOTTOMLEFT", 15, 15)
  end
  info:SetText(text)
  info:Show()
end

local function Setup()
  local page = ProfessionsFrame and ProfessionsFrame.CraftingPage
  local form = page and page.SchematicForm
  if info or not form or not form.Init then return end
  info = form:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  info:SetJustifyH("LEFT")
  info:SetSpacing(4) -- los iconos de moneda hacen las líneas más altas
  info:Hide()
  button = CreateFrame("Button", nil, form, "UIPanelButtonTemplate")
  button:SetSize(80, 22)
  button:SetPoint("TOPLEFT", info, "TOPLEFT", 215, 3)
  button:SetText("Buscar")
  button:SetScript("OnClick", function(self) ns.SearchRecipeReagents(self.recipeID) end)
  button:Hide()
  hooksecurefunc(form, "Init", function(self)
    local ok, err = pcall(Update, self)
    if not ok and not reported then
      reported = true
      ns.ReportError("ventana de profesión", err)
    end
  end)
end

-- Lo que acabas de ver en la subasta cambia las cuentas de la receta abierta.
function ns.OnLivePrices()
  if lastForm and info and lastForm.IsShown and lastForm:IsShown() then
    local ok, err = pcall(Update, lastForm)
    if not ok then ns.ReportError("ventana de profesión", err) end
  end
end

-- La ventana de profesiones de Blizzard se carga la primera vez que se abre.
ns.On("ADDON_LOADED", function(_, name)
  if name == "Blizzard_Professions" then Setup() end
end)
ns.On("PLAYER_LOGIN", Setup)
