-- Pestaña «Libranzas» en la subasta: las misiones de libranza del artesano, de la más barata a la
-- más cara. Cada misión se coge con la libranza y se entrega con el objeto que pide: lo que cuesta es
-- la libranza más el objeto, los dos de la subasta (lo que acabas de ver en ella o, si no, los
-- precios del motor, como el tooltip). Qué pide cada una, su zona y los grupos de zonas pegadas los
-- pone el motor (writs en Generated.lua, de conocimiento/libranzas.json).
-- Dos órdenes, con los botones de arriba a la izquierda:
--   Por zonas:   cada grupo de zonas pegadas (del más barato al más caro de media por misión: uno de
--                6 misiones no sale más caro que uno de 1 solo por tener más), dentro sus zonas (también
--                por la media) y dentro
--                de cada zona sus misiones (libranza y, debajo, el objeto), de la más barata a la más cara.
--   Más baratas: todas las misiones de la más barata a la más cara, con la zona encima; si seguidas
--                caen en la misma zona, van juntas bajo ella.
-- Al pulsar una misión se buscan en la subasta su libranza y su objeto; al pulsar una zona o un grupo,
-- los de todas sus misiones. Al abrirlos se marca la cantidad, como con el botón Buscar de la profesión.
local ADDON, ns = ...

local W = {}
ns.Writs = W

local ROWS, ROW_HEIGHT = 21, 18
local HEADER_Y = 36  -- los títulos de las columnas, debajo de los botones de orden
local COLUMNS = {
  { title = "Zona y misiones", width = 310 },
  { title = "Profesión", width = 80 },
  { title = "Precio", width = 90 },
  { title = "Total", width = 95 },
  { title = "Media", width = 85 },
  { title = "Misiones", width = 60 },
}
local SORTS = { zonas = "Por zonas", baratas = "Más baratas" }
local WRIT_PREFIX = "^Libranza del artesano: "

-- Los grupos y las zonas, con fondo propio para que se distingan de las misiones.
local BACKGROUNDS = { group = { 0.40, 0.30, 0.05, 0.75 }, zone = { 0.10, 0.22, 0.38, 0.75 } }
local LINE_KIND = function(line) return line.kind end

local tab, panel, countText
local rowFrames, sortButtons = {}, {}
local offset = 0

local function Data()
  local gen = PitiGoldsGenerated
  return type(gen) == "table" and type(gen.writs) == "table" and gen.writs or nil
end

local function NameOf(itemID, fallback)
  return ns.ItemNameByID(itemID) or fallback or ("objeto " .. itemID)
end

-- El orden elegido, guardado entre sesiones.
function W.Sort()
  local db = PitiGoldsDB
  local sort = type(db) == "table" and db.writSort or nil
  return SORTS[sort] and sort or "zonas"
end

function W.SetSort(sort)
  if not SORTS[sort] then return end
  if type(PitiGoldsDB) == "table" then PitiGoldsDB.writSort = sort end
  offset = 0
  W.Refresh()
end

-- Menos a más; lo que no tiene precio (nil), al final.
local function Cheaper(a, b, nameA, nameB)
  if (a == nil) ~= (b == nil) then return a ~= nil end
  if a and a ~= b then return a < b end
  return nameA < nameB
end

-- Las misiones con sus precios, de la más barata a la más cara (sin precio, al final). Cada una: id
-- (la libranza), writName, writPrice, target (el objeto), qty, name, itemPrice (por la cantidad),
-- total, prof, zone, npc.
function W.Quests()
  local quests = {}
  local data = Data()
  for writID, d in pairs(data and data.list or {}) do
    local target, qty = tonumber(d[1]), tonumber(d[2]) or 1
    if target then
      local q = {
        id = writID, target = target, qty = qty, name = NameOf(target, d[3]),
        writName = NameOf(writID, d[3] and ("Libranza del artesano: " .. d[3]) or nil),
        prof = d[4] or "", zone = d[5] or "?", npc = d[6] or "",
      }
      q.writPrice = ns.MarketPrice(writID)
      local unit = ns.MarketPrice(target)
      q.itemPrice = unit and unit * qty or nil
      if q.writPrice and q.itemPrice then q.total = q.writPrice + q.itemPrice end
      quests[#quests + 1] = q
    end
  end
  table.sort(quests, function(a, b) return Cheaper(a.total, b.total, a.name, b.name) end)
  return quests
end

-- Suma lo que tiene precio; missing = cuántas misiones no lo tienen (la suma real es mayor) y avg,
-- lo que cuesta de media cada misión con precio (nil si ninguna lo tiene).
local function Sum(quests)
  local sum, missing = 0, 0
  for _, q in ipairs(quests) do
    if q.total then sum = sum + q.total else missing = missing + 1 end
  end
  local priced = #quests - missing
  return sum, missing, priced > 0 and sum / priced or nil
end

local function Node(kind, name, quests, extra)
  local node = extra or {}
  node.kind, node.name, node.quests = kind, name, quests
  node.sum, node.missing, node.avg = Sum(quests)
  return node
end

-- Zonas y grupos, de menos a más de media por misión.
local function CheaperOnAverage(a, b)
  return Cheaper(a.avg, b.avg, a.name, b.name)
end

-- Grupos de zonas pegadas, del más barato al más caro de media por misión. Cada uno: name, zones (de
-- la más barata a la más cara de media, cada una con sus misiones), quests, sum, missing, avg. Las zonas que no están en ningún grupo
-- del motor van solas.
function W.Groups()
  local byZone, zoneOrder = {}, {}
  for _, q in ipairs(W.Quests()) do
    if not byZone[q.zone] then
      byZone[q.zone] = {}
      zoneOrder[#zoneOrder + 1] = q.zone
    end
    table.insert(byZone[q.zone], q)  -- ya van de la más barata a la más cara
  end
  local data, used, groups = Data(), {}, {}
  local function AddGroup(zoneNames)
    local zones, quests = {}, {}
    for _, z in ipairs(zoneNames) do
      if byZone[z] and not used[z] then
        used[z] = true
        zones[#zones + 1] = Node("zone", z, byZone[z])
        for _, q in ipairs(byZone[z]) do quests[#quests + 1] = q end
      end
    end
    if #zones == 0 then return end
    table.sort(zones, CheaperOnAverage)
    local names = {}
    for i, z in ipairs(zones) do names[i] = z.name end
    groups[#groups + 1] = Node("group", table.concat(names, " y "), quests, { zones = zones })
  end
  for _, g in ipairs(data and data.groups or {}) do AddGroup(g) end
  for _, z in ipairs(zoneOrder) do AddGroup({ z }) end
  table.sort(groups, CheaperOnAverage)
  return groups
end

local function AddQuest(lines, q, depth)
  lines[#lines + 1] = { kind = "writ", quest = q, depth = depth, quests = { q } }
  lines[#lines + 1] = { kind = "item", quest = q, depth = depth, quests = { q } }
end

-- Las líneas de la ventana en el orden elegido: grupos ({ kind = "group" }), zonas ({ kind = "zone" })
-- y, de cada misión, la libranza ({ kind = "writ" }) y el objeto ({ kind = "item" }). Cada línea
-- lleva en quests las misiones que se buscan al pulsarla.
function W.Lines(sort)
  local lines = {}
  if (sort or W.Sort()) == "baratas" then
    local current
    for _, q in ipairs(W.Quests()) do
      if not current or current.name ~= q.zone then
        current = Node("zone", q.zone, {}, { depth = 0 })
        lines[#lines + 1] = current
      end
      table.insert(current.quests, q)
      AddQuest(lines, q, 1)
    end
    -- Las sumas, con todas las misiones de cada tramo ya dentro.
    for _, line in ipairs(lines) do
      if line.kind == "zone" then line.sum, line.missing, line.avg = Sum(line.quests) end
    end
    return lines
  end
  for _, g in ipairs(W.Groups()) do
    local depth = 0
    if #g.zones > 1 then
      g.depth = 0
      lines[#lines + 1] = g
      depth = 1
    end
    for _, z in ipairs(g.zones) do
      z.depth = depth
      lines[#lines + 1] = z
      for _, q in ipairs(z.quests) do AddQuest(lines, q, depth + 1) end
    end
  end
  return lines
end

local function Money(value, missing)
  return (missing and missing > 0 and "≥ " or "") .. ns.Money(value)
end

local function Indent(depth)
  return string.rep("    ", depth or 0)
end

-- El texto de cada columna de una línea (también para las pruebas).
function W.Cells(line)
  local kind = line.kind
  if kind == "group" or kind == "zone" then
    local color = kind == "group" and "|cffffd100" or "|cffffffff"
    local count = #line.quests
    return {
      Indent(line.depth) .. color .. line.name .. "|r",
      "",
      "",
      line.sum > 0 and Money(line.sum, line.missing) or "|cff999999sin precio|r",
      line.avg and ("|cff40ff40" .. ns.Money(math.floor(line.avg + 0.5)) .. "|r") or "",
      tostring(count),
    }
  end
  local q = line.quest
  if kind == "writ" then
    return {
      Indent(line.depth) .. "|cff40c0ff" .. q.writName:gsub(WRIT_PREFIX, "Libranza: ") .. "|r",
      q.prof,
      q.writPrice and ns.Money(q.writPrice) or "|cff999999sin precio|r",
      q.total and ("|cff40ff40" .. ns.Money(q.total) .. "|r") or "",
      "",
      "",
    }
  end
  local what = q.qty > 1 and ("%d × %s"):format(q.qty, q.name) or q.name
  return {
    Indent(line.depth) .. "|cffbbbbbb  Entregar: " .. what .. "|r",
    "",
    q.itemPrice and ("|cffbbbbbb" .. ns.Money(q.itemPrice) .. "|r") or "|cff999999sin precio|r",
    "",
    "",
    "",
  }
end

-- Una línea por misión para el chat (/pg libranzas) y las pruebas.
function W.Line(q)
  local what = q.qty > 1 and ("%d × %s"):format(q.qty, q.name) or q.name
  if not q.total then
    return ("%s (%s): sin precio %s"):format(what, q.zone, q.writPrice and "del objeto" or "de la libranza")
  end
  return ("%s  %s (%s): libranza %s + objeto %s"):format(
    ns.Money(q.total), what, q.zone, ns.Money(q.writPrice), ns.Money(q.itemPrice))
end

-- Busca en la subasta las libranzas y los objetos de unas misiones (las de una línea) y los pone en
-- la lista de la compra.
function W.Buy(quests)
  if not quests or #quests == 0 then return end
  local search = { items = {}, names = {}, need = {}, nameOf = {} }
  local function Add(id, qty, name)
    if not search.need[id] then
      search.items[#search.items + 1] = id
      search.names[#search.names + 1] = name
      search.nameOf[id] = name
    end
    search.need[id] = (search.need[id] or 0) + qty
  end
  for _, q in ipairs(quests) do
    Add(q.id, 1, q.writName)
    Add(q.target, q.qty, q.name)
  end
  -- Los resultados salen en Comprar, debajo de la pestaña.
  if ns.ahOpen then W.Hide() end
  ns.ShopAndSearch(search, "misiones")
end

-- El color de fondo de una línea (nil: el de filas alternas).
function W.Background(line)
  return BACKGROUNDS[LINE_KIND(line)]
end

-- La ventana ------------------------------------------------------------------------------

local function ShowTooltip(frame)
  local line = frame.line
  if not (line and GameTooltip) then return end
  GameTooltip:SetOwner(frame, "ANCHOR_RIGHT")
  if line.kind == "group" or line.kind == "zone" then
    GameTooltip:AddLine(line.name)
    GameTooltip:AddLine(("%d misiones%s."):format(#line.quests,
      line.missing > 0 and (", %d sin precio (el total real es mayor)"):format(line.missing) or ""), 1, 1, 1)
    if line.avg then
      GameTooltip:AddLine(("De media, %s por misión."):format(ns.Money(math.floor(line.avg + 0.5))), 1, 1, 1)
    end
    GameTooltip:AddLine("Pulsa para buscar en la subasta las libranzas y los objetos de todas.", 0.6, 0.6, 0.6, true)
  else
    local q = line.quest
    GameTooltip:AddLine(q.writName)
    GameTooltip:AddLine(("%s · se entrega en %s%s."):format(q.prof, q.zone, q.npc ~= "" and (" a " .. q.npc) or ""), 1, 1, 1)
    GameTooltip:AddLine("Pulsa para buscar en la subasta la libranza y el objeto.", 0.6, 0.6, 0.6)
  end
  GameTooltip:Show()
end

local function UpdateSortButtons()
  local sort = W.Sort()
  for key, button in pairs(sortButtons) do
    if key == sort then
      if button.Disable then button:Disable() end
    elseif button.Enable then
      button:Enable()
    end
  end
end

-- El fondo de una fila: el de su línea (BACKGROUNDS) o, si no tiene, filas alternas.
local function Paint(frame, line)
  local stripe = frame.stripe
  if not stripe then return end
  local color = line and BACKGROUNDS[LINE_KIND(line)]
  if color then
    stripe:SetColorTexture(color[1], color[2], color[3], color[4])
  elseif frame.odd then
    stripe:SetColorTexture(1, 1, 1, 0.09)
  else
    stripe:SetColorTexture(0, 0, 0, 0.45)
  end
end

function W.Refresh()
  if not panel then return end
  local lines = W.Lines()
  offset = math.max(0, math.min(offset, #lines - ROWS))
  for i, frame in ipairs(rowFrames) do
    local line = lines[i + offset]
    frame.line = line
    Paint(frame, line)
    if line then
      local cells = W.Cells(line)
      for c, cell in ipairs(frame.cells) do cell:SetText(cells[c] or "") end
      frame:Show()
    else
      frame:Hide()
    end
  end
  UpdateSortButtons()
  -- Solo hay texto si no hay nada que enseñar.
  if countText then
    if #lines == 0 then
      countText:SetText("El motor aún no me ha pasado las libranzas: pasa por el PC (python -m motor leer) y haz /reload.")
    else
      countText:SetText("")
    end
  end
end

local function Scroll(delta)
  offset = offset - delta * 5
  W.Refresh()
end

local function SetTabSelected(selected)
  if not tab then return end
  local fn = selected and PanelTemplates_SelectTab or PanelTemplates_DeselectTab
  if fn then pcall(fn, tab) end
end

function W.Show()
  if not panel then return end
  -- Las dos pestañas nuestras ocupan el mismo sitio.
  if ns.Crates and ns.Crates.Hide then ns.Crates.Hide() end
  panel:Show()
  SetTabSelected(true)
  W.Refresh()
end

function W.Hide()
  if panel then panel:Hide() end
  SetTabSelected(false)
end

function W.IsShown()
  return panel ~= nil and panel:IsShown() and true or false
end

local function CreatePanel(af)
  panel = CreateFrame("Frame", "PitiGoldsWritsPanel", af, "BackdropTemplate")
  -- Como la de Cajones: debajo del retrato de la esquina, tapando lo de Blizzard.
  panel:SetPoint("TOPLEFT", af, "TOPLEFT", 4, -60)
  panel:SetPoint("BOTTOMRIGHT", af, "BOTTOMRIGHT", -4, 4)
  panel:SetFrameStrata("HIGH")
  if panel.SetToplevel then panel:SetToplevel(true) end
  local bg = panel:CreateTexture(nil, "BACKGROUND", nil, -8)
  if bg then
    bg:SetAllPoints()
    bg:SetColorTexture(0.06, 0.06, 0.06, 1)
  end
  panel:EnableMouse(true)
  panel:EnableMouseWheel(true)
  panel:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)
  if panel.SetBackdrop then
    panel:SetBackdrop({
      bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
      edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
      edgeSize = 12,
      insets = { left = 3, right = 3, top = 3, bottom = 3 },
    })
    panel:SetBackdropColor(0.05, 0.05, 0.05, 1)
  end

  countText = panel:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  countText:SetPoint("TOPLEFT", panel, "TOPLEFT", 12, -64)
  countText:SetJustifyH("LEFT")

  -- Los dos órdenes, arriba a la izquierda.
  local previous
  for _, key in ipairs({ "zonas", "baratas" }) do
    local b = CreateFrame("Button", nil, panel, "UIPanelButtonTemplate")
    b:SetSize(100, 20)
    b:SetText(SORTS[key])
    if previous then
      b:SetPoint("LEFT", previous, "RIGHT", 4, 0)
    else
      b:SetPoint("TOPLEFT", panel, "TOPLEFT", 12, -8)
    end
    b:SetScript("OnClick", function() W.SetSort(key) end)
    sortButtons[key] = b
    previous = b
  end

  local x = 12
  for _, col in ipairs(COLUMNS) do
    local h = panel:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    h:SetPoint("TOPLEFT", panel, "TOPLEFT", x + 4, -HEADER_Y)
    h:SetText(col.title)
    x = x + col.width
  end

  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, panel)
    row:SetSize(x - 12, ROW_HEIGHT)
    row:SetPoint("TOPLEFT", panel, "TOPLEFT", 12, -HEADER_Y - ROW_HEIGHT * i)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.stripe = row:CreateTexture(nil, "BACKGROUND", nil, -1)
    if row.stripe then row.stripe:SetAllPoints() end
    row.odd = i % 2 == 1
    row.cells = {}
    local cx = 0
    for c, col in ipairs(COLUMNS) do
      local cell = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      cell:SetPoint("LEFT", row, "LEFT", cx + 4, 0)
      cell:SetWidth(col.width - 8)
      cell:SetJustifyH("LEFT")
      if cell.SetWordWrap then cell:SetWordWrap(false) end
      row.cells[c] = cell
      cx = cx + col.width
    end
    row:SetScript("OnClick", function(self)
      if self.line then W.Buy(self.line.quests) end
    end)
    row:SetScript("OnEnter", ShowTooltip)
    row:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    row:EnableMouseWheel(true)
    row:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)
    rowFrames[i] = row
  end
  panel:Hide()
end

-- Va junto a la de Cajones; si no estuviera, junto a la última de Blizzard.
local function LastTab(af)
  if _G.PitiGoldsCratesTab then return _G.PitiGoldsCratesTab end
  local tabs = type(af.Tabs) == "table" and af.Tabs or nil
  if tabs and #tabs > 0 then return tabs[#tabs] end
  return _G.AuctionHouseFrameAuctionsTab
end

local function CreateTab(af)
  local last = LastTab(af)
  -- Dentro de un marco nuestro, para no entrar en la lista Tabs de la subasta (ver Crates.lua).
  local holder = CreateFrame("Frame", nil, af)
  holder:SetAllPoints(af)
  local ok, button = pcall(CreateFrame, "Button", "PitiGoldsWritsTab", holder, "PanelTabButtonTemplate")
  if not ok or not button then
    button = CreateFrame("Button", "PitiGoldsWritsTab", holder, "UIPanelButtonTemplate")
    button:SetSize(90, 22)
  end
  tab = button
  tab:SetText("Libranzas")
  if PanelTemplates_TabResize then pcall(PanelTemplates_TabResize, tab, 0) end
  if last == tab then last = nil end
  if last then
    tab:SetPoint("LEFT", last, "RIGHT", 3, 0)
  else
    tab:SetPoint("TOPLEFT", af, "BOTTOMLEFT", 20, 2)
  end
  tab:SetScript("OnClick", function()
    if W.IsShown() then W.Hide() else W.Show() end
  end)
  SetTabSelected(false)
end

local function Setup()
  local af = AuctionHouseFrame
  if panel or not af then return end
  CreatePanel(af)
  CreateTab(af)
  if af.SetDisplayMode then
    hooksecurefunc(af, "SetDisplayMode", function() W.Hide() end)
  end
end

local function OnAuctionShow()
  local ok, err = pcall(Setup)
  if not ok then ns.ReportError("pestaña Libranzas", err) end
end
ns.On("AUCTION_HOUSE_SHOW", OnAuctionShow)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", OnAuctionShow)

local previousLive = ns.OnLivePrices
function ns.OnLivePrices()
  if previousLive then previousLive() end
  if W.IsShown() then
    local ok, err = pcall(W.Refresh)
    if not ok then ns.ReportError("pestaña Libranzas", err) end
  end
end

ns.Command("libranzas", "las misiones de libranza más baratas", function()
  local quests = W.Quests()
  if #quests == 0 then
    ns.Print("el motor aún no me ha pasado las libranzas: pasa por el PC (python -m motor leer) y haz /reload.")
    return
  end
  ns.Print("misiones de libranza, de la más barata a la más cara:")
  for i = 1, math.min(10, #quests) do ns.Print(W.Line(quests[i])) end
end)
