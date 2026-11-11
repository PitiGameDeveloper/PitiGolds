-- Pestaña «Cajones» en la subasta: los cajones saqueados, del favor de mercader más barato al más
-- caro. Cada cajón se llena con UNO de sus lotes (20 de polvo extraño, o 4 esencias...): cuenta el
-- más barato, más lo que cuesta el cajón, y lo divide entre el favor que da. Qué pide cada uno lo
-- pone el motor (crates en Generated.lua, de conocimiento/cajones.json). Solo cuenta la subasta:
-- lo que acabas de ver en ella o, si no, los precios del motor, como el tooltip.
-- La lista va en árbol: cada cajón y debajo sus lotes, del más barato al más caro (precio por la
-- cantidad que pide). Al pulsar un lote se buscan en la subasta el cajón y ese lote, y al abrirlos
-- se marca la cantidad, como con el botón Buscar de la profesión.
local ADDON, ns = ...

local C = {}
ns.Crates = C

local ROWS, ROW_HEIGHT = 22, 18
local HEADER_Y = 12  -- los títulos de las columnas, arriba del todo
local COLUMNS = {
  { title = "Cajón y lotes", width = 300 },
  { title = "Favor", width = 45 },
  { title = "Cajón", width = 90 },
  { title = "Lote", width = 95 },
  { title = "Total", width = 95 },
  { title = "Por favor", width = 90 },
}
local QUALITY_COLORS = { [1] = "ffffffff", [2] = "ff1eff00", [3] = "ff0070dd" }

-- Las filas de cada cajón, con fondo propio para que se distingan de sus lotes.
local BACKGROUNDS = { crate = { 0.40, 0.30, 0.05, 0.75 } }
local LINE_KIND = function(line) return line.opt and "opt" or "crate" end

local tab, panel, countText
local rowFrames = {}
local offset = 0

local function Crates()
  local gen = PitiGoldsGenerated
  return type(gen) == "table" and type(gen.crates) == "table" and gen.crates or nil
end

local function NameOf(itemID, fallback)
  return ns.ItemNameByID(itemID) or fallback or ("objeto " .. itemID)
end

local function Quality(itemID)
  local get = C_Item and C_Item.GetItemQualityByID
  if not get then return nil end
  local ok, q = pcall(get, itemID)
  return ok and q or nil
end

-- La lista ya calculada, de más barato a más caro por favor; los que no tienen precio, al final.
-- Cada fila: id, name, favor, est, crate (precio del cajón), options (los lotes { id, qty, name,
-- cost, total, perFavor }, del más barato al más caro; sin precio, al final), opt (el más barato),
-- fill (lo que cuesta), total y perFavor.
function C.Rows()
  local rows = {}
  for crateID, d in pairs(Crates() or {}) do
    local row = {
      id = crateID, name = NameOf(crateID, d.name), favor = tonumber(d.favor) or 0,
      est = d.est and true or false, options = {},
    }
    row.crate = ns.MarketPrice(crateID)
    for _, o in ipairs(d.opts or {}) do
      local id, qty = tonumber(o[1]), tonumber(o[2]) or 1
      if id then
        local unit = ns.MarketPrice(id)
        local option = { id = id, qty = qty, name = NameOf(id, o[3]), cost = unit and unit * qty or nil }
        if option.cost and row.crate and row.favor > 0 then
          option.total = row.crate + option.cost
          option.perFavor = option.total / row.favor
        end
        row.options[#row.options + 1] = option
      end
    end
    table.sort(row.options, function(a, b)
      if (a.cost == nil) ~= (b.cost == nil) then return a.cost ~= nil end
      if a.cost and a.cost ~= b.cost then return a.cost < b.cost end
      return a.name < b.name
    end)
    local best = row.options[1]
    if best and best.cost then row.opt, row.fill = best, best.cost end
    if row.crate and row.fill and row.favor > 0 then
      row.total = row.crate + row.fill
      row.perFavor = row.total / row.favor
    end
    rows[#rows + 1] = row
  end
  table.sort(rows, function(a, b)
    if (a.perFavor == nil) ~= (b.perFavor == nil) then return a.perFavor ~= nil end
    if a.perFavor and a.perFavor ~= b.perFavor then return a.perFavor < b.perFavor end
    return a.name < b.name
  end)
  return rows
end

-- «Cajón saqueado: hierbas de oficial» -> «Hierbas de oficial».
local function ShortName(name)
  local short = name:gsub("^Cajón saqueado: ", "")
  return (short:gsub("^%l", string.upper))
end

local function FavorText(row)
  return row.favor .. (row.est and "?" or "")
end

-- Las líneas de la ventana: cada cajón ({ row }) y debajo sus lotes ({ row, opt }).
function C.Lines()
  local lines = {}
  for _, row in ipairs(C.Rows()) do
    lines[#lines + 1] = { row = row }
    for _, opt in ipairs(row.options) do lines[#lines + 1] = { row = row, opt = opt } end
  end
  return lines
end

-- El texto de cada columna de una línea (también para las pruebas).
function C.Cells(line)
  local row, opt = line.row, line.opt
  if not opt then
    local color = QUALITY_COLORS[Quality(row.id) or 1] or QUALITY_COLORS[1]
    return {
      "|c" .. color .. ShortName(row.name) .. "|r",
      FavorText(row),
      row.crate and ns.Money(row.crate) or "|cff999999sin precio|r",
      "",
      row.total and ns.Money(row.total) or "",
      row.perFavor and ("|cff40ff40" .. ns.Money(row.perFavor) .. "|r") or "",
    }
  end
  -- El lote más barato, en verde; los demás, en gris.
  local color = opt == row.opt and "|cff40ff40" or "|cffbbbbbb"
  return {
    "      " .. color .. ("%d × %s"):format(opt.qty, opt.name) .. "|r",
    "",
    "",
    opt.cost and (color .. ns.Money(opt.cost) .. "|r") or "|cff999999sin precio|r",
    opt.total and (color .. ns.Money(opt.total) .. "|r") or "",
    opt.perFavor and (color .. ns.Money(opt.perFavor) .. "|r") or "",
  }
end

-- Una línea por cajón para el chat (/pg cajones) y las pruebas.
function C.Line(row)
  if not row.perFavor then
    return ("%s (%s de favor): sin precio %s"):format(row.name, FavorText(row), row.crate and "de los lotes" or "del cajón")
  end
  return ("%s/favor  %s (%s de favor): cajón %s + %d × %s %s = %s"):format(
    ns.Money(row.perFavor), row.name, FavorText(row), ns.Money(row.crate), row.opt.qty, row.opt.name,
    ns.Money(row.fill), ns.Money(row.total))
end

-- Busca en la subasta el cajón y un lote (optID; sin él, el más barato), y los pone en la lista de
-- la compra.
function C.Buy(crateID, optID)
  local row
  for _, r in ipairs(C.Rows()) do
    if r.id == crateID then row = r break end
  end
  if not row then return end
  local search = { items = { row.id }, names = { row.name }, need = { [row.id] = 1 }, nameOf = { [row.id] = row.name } }
  local opt = row.opt
  for _, o in ipairs(optID and row.options or {}) do
    if o.id == optID then opt = o break end
  end
  if opt then
    search.items[2], search.names[2] = opt.id, opt.name
    search.need[opt.id], search.nameOf[opt.id] = opt.qty, opt.name
  else
    ns.Print("no tengo precio de ningún lote de " .. row.name .. "; busco solo el cajón.")
  end
  -- Los resultados salen en Comprar, debajo de la pestaña.
  if ns.ahOpen then C.Hide() end
  ns.ShopAndSearch(search, "cajones")
end

-- El color de fondo de una línea (nil: el de filas alternas).
function C.Background(line)
  return BACKGROUNDS[LINE_KIND(line)]
end

-- La ventana ------------------------------------------------------------------------------

local function ShowTooltip(frame)
  local line = frame.line
  if not (line and GameTooltip) then return end
  local row, opt = line.row, line.opt
  GameTooltip:SetOwner(frame, "ANCHOR_RIGHT")
  GameTooltip:AddLine(row.name)
  GameTooltip:AddLine(("Da %s de favor%s."):format(FavorText(row), row.est and " (sin comprobar)" or ""), 1, 1, 1)
  if opt then
    GameTooltip:AddLine(("Pulsa para buscar el cajón y %d %s en la subasta."):format(opt.qty, opt.name), 0.6, 0.6, 0.6)
  else
    GameTooltip:AddLine("Se llena con uno de los lotes de debajo. Pulsa para buscar el cajón y el más barato.",
      0.6, 0.6, 0.6, true)
  end
  GameTooltip:Show()
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

function C.Refresh()
  if not panel then return end
  local lines = C.Lines()
  local rows = C.Rows()
  offset = math.max(0, math.min(offset, #lines - ROWS))
  for i, frame in ipairs(rowFrames) do
    local line = lines[i + offset]
    frame.line = line
    Paint(frame, line)
    if line then
      local cells = C.Cells(line)
      for c, cell in ipairs(frame.cells) do cell:SetText(cells[c] or "") end
      frame:Show()
    else
      frame:Hide()
    end
  end
  -- Solo hay texto si no hay nada que enseñar.
  if countText then
    countText:SetText(#rows == 0
      and "El motor aún no me ha pasado los cajones: pasa por el PC (python -m motor leer) y haz /reload." or "")
  end
end

local function Scroll(delta)
  offset = offset - delta * 5
  C.Refresh()
end

local function SetTabSelected(selected)
  if not tab then return end
  local fn = selected and PanelTemplates_SelectTab or PanelTemplates_DeselectTab
  if fn then pcall(fn, tab) end
end

function C.Show()
  if not panel then return end
  -- Las dos pestañas nuestras ocupan el mismo sitio.
  if ns.Writs and ns.Writs.Hide then ns.Writs.Hide() end
  panel:Show()
  SetTabSelected(true)
  C.Refresh()
end

function C.Hide()
  if panel then panel:Hide() end
  SetTabSelected(false)
end

function C.IsShown()
  return panel ~= nil and panel:IsShown() and true or false
end

local function CreatePanel(af)
  panel = CreateFrame("Frame", "PitiGoldsCratesPanel", af, "BackdropTemplate")
  -- Debajo del retrato de la esquina; tapa la barra de búsqueda y todo lo de Blizzard.
  panel:SetPoint("TOPLEFT", af, "TOPLEFT", 4, -60)
  panel:SetPoint("BOTTOMRIGHT", af, "BOTTOMRIGHT", -4, 4)
  -- Por encima de la subasta y de todo lo que lleva dentro (sus listas tienen niveles altos).
  panel:SetFrameStrata("HIGH")
  if panel.SetToplevel then panel:SetToplevel(true) end
  -- Fondo opaco propio: no depende de que el cliente tenga BackdropTemplate.
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
  countText:SetPoint("TOPLEFT", panel, "TOPLEFT", 12, -40)
  countText:SetJustifyH("LEFT")

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
      local line = self.line
      if line then C.Buy(line.row.id, line.opt and line.opt.id) end
    end)
    row:SetScript("OnEnter", ShowTooltip)
    row:SetScript("OnLeave", function() if GameTooltip then GameTooltip:Hide() end end)
    row:EnableMouseWheel(true)
    row:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)
    rowFrames[i] = row
  end
  panel:Hide()
end

-- La última pestaña de Blizzard (Comprar, Vender, Subastas...), para poner la nuestra a su lado.
local function LastTab(af)
  local tabs = type(af.Tabs) == "table" and af.Tabs or nil
  if tabs and #tabs > 0 then return tabs[#tabs] end
  return _G.AuctionHouseFrameAuctionsTab
end

local function CreateTab(af)
  -- La última de Blizzard se busca antes de crear la nuestra.
  local last = LastTab(af)
  -- La plantilla de pestaña se apunta sola en la lista Tabs de su padre: con la subasta de padre
  -- entraría en la de Blizzard (y la última pestaña sería ella misma). Va dentro de un marco nuestro.
  local holder = CreateFrame("Frame", nil, af)
  holder:SetAllPoints(af)
  local ok, button = pcall(CreateFrame, "Button", "PitiGoldsCratesTab", holder, "PanelTabButtonTemplate")
  if not ok or not button then
    button = CreateFrame("Button", "PitiGoldsCratesTab", holder, "UIPanelButtonTemplate")
    button:SetSize(90, 22)
  end
  tab = button
  tab:SetText("Cajones")
  if PanelTemplates_TabResize then pcall(PanelTemplates_TabResize, tab, 0) end
  if last == tab then last = nil end
  if last then
    tab:SetPoint("LEFT", last, "RIGHT", 3, 0)
  else
    tab:SetPoint("TOPLEFT", af, "BOTTOMLEFT", 20, 2)
  end
  tab:SetScript("OnClick", function()
    if C.IsShown() then C.Hide() else C.Show() end
  end)
  SetTabSelected(false)
end

local function Setup()
  local af = AuctionHouseFrame
  if panel or not af then return end
  CreatePanel(af)
  CreateTab(af)
  -- Cualquier pestaña de Blizzard (o una búsqueda, que pasa a Comprar) cierra la nuestra.
  if af.SetDisplayMode then
    hooksecurefunc(af, "SetDisplayMode", function() C.Hide() end)
  end
end

local function OnAuctionShow()
  local ok, err = pcall(Setup)
  if not ok then ns.ReportError("pestaña Cajones", err) end
end
ns.On("AUCTION_HOUSE_SHOW", OnAuctionShow)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", OnAuctionShow)

-- Lo que acabas de ver en la subasta cambia las cuentas.
local previousLive = ns.OnLivePrices
function ns.OnLivePrices()
  if previousLive then previousLive() end
  if C.IsShown() then
    local ok, err = pcall(C.Refresh)
    if not ok then ns.ReportError("pestaña Cajones", err) end
  end
end

ns.Command("cajones", "los cajones saqueados que dan el favor más barato", function()
  local rows = C.Rows()
  if #rows == 0 then
    ns.Print("el motor aún no me ha pasado los cajones: pasa por el PC (python -m motor leer) y haz /reload.")
    return
  end
  ns.Print("cajones saqueados, del favor más barato al más caro:")
  for i = 1, math.min(10, #rows) do ns.Print(C.Line(rows[i])) end
end)
