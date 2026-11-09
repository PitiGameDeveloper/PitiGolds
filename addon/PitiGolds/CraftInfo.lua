-- En la ventana de profesión, debajo de los materiales de la receta elegida: cuánto cuesta
-- fabricarla (materiales al mejor precio, de subasta o de vendedor) y cuánto se gana vendiendo
-- lo fabricado, ya sin la comisión de la subasta. Las cuentas las hace el motor (recipes en
-- Generated.lua), con los mismos precios que el informe. Al lado, el botón Buscar busca en la
-- subasta los materiales de la receta (si está cerrada, al abrirla).
local ADDON, ns = ...

-- Texto del recuadro para una receta, o nil si el motor no tiene su coste.
function ns.CraftInfoText(recipeID)
  local gen = PitiGoldsGenerated
  local data = recipeID and type(gen) == "table" and gen.recipes and gen.recipes[recipeID]
  if not data then return nil end
  local cost, profit = data:match("^(%d+),(%-?%d*)$")
  if not cost then return nil end
  local text = "Fabricar: |cffffffff" .. ns.Money(cost) .. "|r"
  profit = tonumber(profit)
  if profit then
    text = text .. "\nGanancia: " .. (profit >= 0 and "|cff40ff40" or "|cffff4040") .. ns.Money(profit) .. "|r"
  end
  return text
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
  local search = { items = {}, names = {} }
  local seen = {}
  for _, slot in ipairs(s.reagentSlotSchematics or {}) do
    if slot.required or slot.reagentType == BASIC_REAGENT then
      for _, r in ipairs(slot.reagents or {}) do
        if r.itemID and not seen[r.itemID] then
          seen[r.itemID] = true
          search.items[#search.items + 1] = r.itemID
          search.names[#search.names + 1] = ns.ItemNameByID(r.itemID) or ("objeto " .. r.itemID)
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

local info, button
local reported = false

local function Update(form)
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
    info:SetPoint("TOPLEFT", anchor, "BOTTOMLEFT", 0, -10)
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
  info:SetSpacing(2)
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

-- La ventana de profesiones de Blizzard se carga la primera vez que se abre.
ns.On("ADDON_LOADED", function(_, name)
  if name == "Blizzard_Professions" then Setup() end
end)
ns.On("PLAYER_LOGIN", Setup)
