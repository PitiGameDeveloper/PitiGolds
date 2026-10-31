-- Ventana de métodos: el mejor farmeo y las pestañas de farmeos y crafteos que calcula el
-- motor (PitiGoldsGenerated.methods). Al pulsar un método se despliega lo que sabe de él;
-- en los crafteos, además, los pasos para hacerlo con tus personajes, que se rehacen al
-- momento con «Actualizar» (por ejemplo, en cuanto aprendes la receta).
local ADDON, ns = ...

local M = {}
ns.Methods = M

local WIDTH, HEIGHT = 720, 560
local ROWS, ROW_HEIGHT = 11, 18
local COLORS = {
  verde = { 0.2, 0.85, 0.2 }, amarillo = { 1, 0.82, 0.1 }, naranja = { 1, 0.5, 0.1 },
  rojo = { 0.9, 0.15, 0.15 },
}
local COLOR_RANK = { verde = 0, amarillo = 1, naranja = 2, rojo = 3 }
local STATE_COLORS = { mejor = "ff33dd33", preparar = "ffffd11a", investigar = "ffff4040", sin_datos = "ffaaaaaa" }

local COLUMNS = {
  farms = {
    { title = "Farmeo", width = 250, key = "name" },
    { title = "Nota", width = 40, key = "score" },
    { title = "Rinde", width = 50, key = "color" },
    { title = "Oro/h", width = 110, key = "gph" },
    { title = "¿Puedo?", width = 170, key = "who" },
    { title = "Nivel", width = 70, key = "level" },
  },
  crafts = {
    { title = "Crafteo", width = 250, key = "name" },
    { title = "Nota", width = 40, key = "score" },
    { title = "Beneficio/u", width = 110, key = "profit" },
    { title = "Al día", width = 60, key = "perDay" },
    { title = "¿Puedo?", width = 230, key = "color" },
  },
}

local window, verdictText, freshText, detailText, detailScroll, detailChild, updateButton, measureButton
local tabButtons, headerButtons, rowFrames = {}, {}, {}
local state = { tab = "farms", offset = 0, selected = nil, sort = nil, desc = false }

local function Data()
  local gen = PitiGoldsGenerated
  return type(gen) == "table" and type(gen.methods) == "table" and gen.methods or nil
end

local function Ago(t)
  if not t or t == 0 then return "nunca" end
  local minutes = math.floor((time() - t) / 60)
  if minutes < 1 then return "ahora" end
  if minutes < 60 then return ("hace %d min"):format(minutes) end
  if minutes < 48 * 60 then return ("hace %d h"):format(math.floor(minutes / 60)) end
  return ("hace %d días"):format(math.floor(minutes / 1440))
end

local function Colored(text, color)
  local c = COLORS[color]
  if not c then return text end
  return ("|cff%02x%02x%02x%s|r"):format(c[1] * 255, c[2] * 255, c[3] * 255, text)
end

-- Personajes e inventario (lo que el addon ha visto de cada uno) -------------------------

local function CharName(key)
  local c = key and PitiGoldsDB.characters[key]
  return (c and c.name) or (key and key:match("^[^-]+")) or "?"
end

local function AddItems(total, items)
  if type(items) ~= "table" then return end
  for itemID, n in pairs(items) do
    if type(itemID) == "number" and type(n) == "number" then total[itemID] = (total[itemID] or 0) + n end
  end
end

-- Lo que tiene cada personaje (bolsas, banco, buzón y lo que le han enviado) y el banco de banda.
local function Holdings()
  local byChar = {}
  for key, c in pairs(PitiGoldsDB.characters) do
    local inv, total = c.inventory or {}, {}
    for _, where in ipairs({ "bags", "bank", "mail" }) do
      if type(inv[where]) == "table" then AddItems(total, inv[where].items) end
    end
    for _, mail in ipairs(inv.mailIncoming or {}) do AddItems(total, mail.items) end
    byChar[key] = total
  end
  local warband = {}
  local bank = PitiGoldsDB.account and PitiGoldsDB.account.warbandBank
  if type(bank) == "table" then AddItems(warband, bank.items) end
  return byChar, warband
end

local function KnowsRecipe(key, recipeID)
  if key == ns.charKey then
    if IsPlayerSpell and IsPlayerSpell(recipeID) then return true end
    local T = C_TradeSkillUI
    if T and T.GetRecipeInfo then
      local ok, info = pcall(T.GetRecipeInfo, recipeID)
      if ok and type(info) == "table" and info.learned then return true end
    end
  end
  local c = PitiGoldsDB.characters[key]
  for _, prof in pairs(c and c.professions or {}) do
    for _, id in ipairs(prof.known or {}) do
      if id == recipeID then return true end
    end
  end
  return false
end

local function Crafters(row)
  local list, seen = {}, {}
  for _, key in ipairs(row.knownBy or {}) do
    if PitiGoldsDB.characters[key] and not seen[key] then list[#list + 1], seen[key] = key, true end
  end
  for key in pairs(PitiGoldsDB.characters) do
    if not seen[key] and KnowsRecipe(key, row.recipe) then list[#list + 1], seen[key] = key, true end
  end
  -- Primero el personaje con el que estás jugando.
  table.sort(list, function(a, b)
    if (a == ns.charKey) ~= (b == ns.charKey) then return a == ns.charKey end
    return a < b
  end)
  return list
end

local function LiveSkill(key, line, fallback)
  local c = key and PitiGoldsDB.characters[key]
  local best = fallback or 0
  for id, prof in pairs(c and c.professions or {}) do
    if (id == line or prof.parentID == line) and (prof.skill or 0) > best then best = prof.skill end
  end
  return best
end

-- Pasos de un crafteo ---------------------------------------------------------------------

local function PriceText(price)
  return price and ("~" .. ns.Money(price)) or "precio desconocido"
end

local function JoinItems(list)
  local parts = {}
  for _, it in ipairs(list) do
    local text = ("x%d %s"):format(it.n, it.name)
    if it.price then text = text .. " (" .. PriceText(it.price) .. " c/u)" end
    parts[#parts + 1] = text
  end
  return table.concat(parts, ", ")
end

local function StepsToLearn(row, steps)
  local who = row.who and CharName(row.who) or "un personaje con " .. (row.prof or "la profesión")
  local skill = LiveSkill(row.who, row.line, row.skill)
  for _, line in ipairs(row.prep or {}) do steps[#steps + 1] = line end
  local learn = row.learn or {}
  local intro = ("Conéctate con %s (%s %d)"):format(who, row.prof or "?", skill)
  if learn.way == "instructor" or learn.way == "profesion" then
    steps[#steps + 1] = intro .. " y aprende la receta con el instructor de " .. (row.prof or "la profesión") .. "."
  elseif learn.way == "vendedor" and learn.vendor then
    local where = learn.zone and (", viaja a " .. learn.zone) or ""
    steps[#steps + 1] = ("%s%s y cómprale «%s» a %s%s. Apréndela."):format(intro, where, learn.itemName or "la receta",
      learn.vendor, learn.price and (" por " .. ns.Money(learn.price)) or "")
  elseif learn.way == "subasta" then
    steps[#steps + 1] = ("%s, compra «%s» en la subasta (%s) y apréndela."):format(intro,
      learn.itemName or "la receta", PriceText(learn.price))
  else
    steps[#steps + 1] = intro .. ". " .. (learn.text or "Consigue la receta.")
  end
  steps[#steps + 1] = "Cuando la hayas aprendido (abre la profesión una vez), pulsa Actualizar."
end

local function StepsToCraft(row, crafter, steps)
  local n = row.craftsDay or 1
  local byChar, warband = Holdings()
  local mine = byChar[crafter] or {}
  local transfers, transferOrder, fromWarband, vendors, vendorOrder, auction, currencies = {}, {}, {}, {}, {}, {}, {}
  local ready = true
  for _, r in ipairs(row.reagents or {}) do
    local need = (r.qty or 1) * n
    if r.src == "divisa" or not r.id then
      currencies[#currencies + 1] = ("%d %s"):format(need, r.name or "divisa")
    else
      local remaining = need - math.min(need, mine[r.id] or 0)
      if remaining > 0 then ready = false end
      -- De tus otros personajes, empezando por el que más tiene.
      local holders = {}
      for key, items in pairs(byChar) do
        if key ~= crafter and (items[r.id] or 0) > 0 then holders[#holders + 1] = key end
      end
      table.sort(holders, function(a, b) return (byChar[a][r.id] or 0) > (byChar[b][r.id] or 0) end)
      for _, key in ipairs(holders) do
        if remaining <= 0 then break end
        local take = math.min(remaining, byChar[key][r.id])
        if not transfers[key] then transfers[key], transferOrder[#transferOrder + 1] = {}, key end
        table.insert(transfers[key], { n = take, name = r.name })
        remaining = remaining - take
      end
      if remaining > 0 and (warband[r.id] or 0) > 0 then
        local take = math.min(remaining, warband[r.id])
        table.insert(fromWarband, { n = take, name = r.name })
        remaining = remaining - take
      end
      if remaining > 0 then
        if r.src == "vendedor" then
          local key = r.vendor or "?"
          if not vendors[key] then
            vendors[key], vendorOrder[#vendorOrder + 1] = { zone = r.zone, items = {} }, key
          end
          table.insert(vendors[key].items, { n = remaining, name = r.name, price = r.price })
        else
          table.insert(auction, { n = remaining, name = r.name, price = r.price })
        end
      end
    end
  end

  local who = CharName(crafter)
  steps[#steps + 1] = ("Hoy: %d × %s con %s%s."):format(n, row.name, who,
    row.goldDay and (", unos " .. ns.Money(row.goldDay) .. " de beneficio") or "")
  if ready then steps[#steps + 1] = who .. " ya tiene todos los materiales." end
  for _, key in ipairs(transferOrder) do
    local verb = key == ns.charKey and "Envía" or ("Conéctate con %s y envía"):format(CharName(key))
    steps[#steps + 1] = ("%s por correo a %s: %s."):format(verb, who, JoinItems(transfers[key]))
  end
  if crafter ~= ns.charKey then steps[#steps + 1] = ("Conéctate con %s."):format(who) end
  if #fromWarband > 0 then steps[#steps + 1] = "Saca del banco de banda: " .. JoinItems(fromWarband) .. "." end
  for _, key in ipairs(vendorOrder) do
    local v = vendors[key]
    if key == "?" then
      steps[#steps + 1] = "Compra a un vendedor: " .. JoinItems(v.items)
        .. ". Aún no sé cuál: cuando lo encuentres, abre su ventana y lo apuntaré."
    else
      local where = v.zone and ("Viaja a " .. v.zone .. ", habla con ") or "Habla con "
      steps[#steps + 1] = ("%s%s y compra %s."):format(where, key, JoinItems(v.items))
    end
  end
  if #auction > 0 then
    steps[#steps + 1] = "Ve a la subasta y compra " .. JoinItems(auction) .. "."
  end
  if #currencies > 0 then steps[#steps + 1] = "Necesitas además " .. table.concat(currencies, ", ") .. "." end
  steps[#steps + 1] = ("Fabrica x%d %s con %s."):format(n, row.name, who)
  local units = math.floor(n * (row.outputQty or 1) + 0.5)
  local post = ("Ponlo en la subasta: x%d a %s c/u"):format(units, PriceText(row.sellPrice))
  if row.perDay then post = post .. (" (el mercado se lleva unas %s al día: no pongas más)"):format(row.perDay) end
  steps[#steps + 1] = post .. "."
  if row.cooldown then steps[#steps + 1] = ("Tiene una espera de %s h entre fabricaciones."):format(row.cooldown) end
end

function M.CraftSteps(row)
  local steps = {}
  local crafters = Crafters(row)
  if #crafters > 0 then
    StepsToCraft(row, crafters[1], steps)
  else
    StepsToLearn(row, steps)
  end
  return steps, #crafters > 0
end

-- Filas y orden -----------------------------------------------------------------------------

local function Rows()
  local data = Data()
  local list = {}
  for i, row in ipairs(data and data[state.tab] or {}) do
    list[#list + 1] = row
    row._order = i
  end
  local key = state.sort
  if key then
    local function value(row)
      if key == "color" then return -(COLOR_RANK[row._color or row.color] or 9) end
      if key == "who" then return row.who and 1 or 0 end
      if key == "name" then return row.name or "" end
      return row[key] or -1
    end
    table.sort(list, function(a, b)
      local va, vb = value(a), value(b)
      if va == vb then return a._order < b._order end
      if type(va) ~= type(vb) then return tostring(va) < tostring(vb) end
      if key == "name" then return (va < vb) ~= state.desc end
      return (va > vb) ~= state.desc
    end)
  end
  return list
end

local function FarmCells(row)
  local star = row.measured and "" or "*"
  local name = row.name .. (row.pending and " |cffaaaaaa(en espera)|r" or "")
  local rinde = row.color and Colored(row.color == "verde" and "Mucho" or row.color == "amarillo" and "Algo" or "No",
    row.color) .. star or "?"
  local gph = row.gph and (ns.Money(row.gph) .. star) or "?"
  local who
  if row.who then
    who = Colored("Sí", "verde") .. ": " .. row.who .. (row.req ~= "" and (" (" .. row.req .. ")") or "")
  else
    who = Colored("No", "rojo") .. (row.req ~= "" and (" (" .. row.req .. ")") or "")
  end
  local level = row.level and tostring(row.level) or ""
  if row.minLevel and row.minLevel ~= row.level then level = level .. " (" .. row.minLevel .. ")" end
  return { name, row.score and tostring(row.score) or "-", rinde, gph, who, level }
end

local function CraftCells(row)
  local profit = row.profit and (ns.Money(row.profit) .. (row.approx and "*" or "")) or "?"
  local perDay = row.perDay and tostring(row.perDay) or "?"
  local color = row._color or row.color
  local label = { verde = "Sí", amarillo = "Casi", naranja = "Falta algo", rojo = "Falta mucho" }
  local who = row._crafter and CharName(row._crafter) or row.whoName
  local text = Colored(label[color] or "?", color) .. (who and (": " .. who) or "")
  return { row.name .. " |cffaaaaaa(" .. (row.prof or "?") .. ")|r", row.score and tostring(row.score) or "-",
    profit, perDay, text }
end

-- Ventana ------------------------------------------------------------------------------------

local function DetailFor(row)
  local lines = {}
  if state.tab == "crafts" then
    local steps, known = M.CraftSteps(row)
    row._color = known and "verde" or row.color
    row._crafter = known and Crafters(row)[1] or nil
    lines[#lines + 1] = known and "|cffffd100Pasos:|r" or "|cffffd100Para poder hacerlo:|r"
    for i, step in ipairs(steps) do lines[#lines + 1] = ("%d. %s"):format(i, step) end
    lines[#lines + 1] = ""
  elseif row.lacking and row.lacking ~= "" and row.closest then
    lines[#lines + 1] = ("|cffffd100A %s le falta:|r %s"):format(row.closest, row.lacking)
  end
  for _, d in ipairs(row.details or {}) do lines[#lines + 1] = d end
  return table.concat(lines, "\n")
end

local function ShowDetail()
  local rows = Rows()
  local row
  for _, r in ipairs(rows) do
    if (r.key or r.recipe) == state.selected then row = r end
  end
  if not row then
    detailText:SetText("|cffaaaaaaPulsa un método para ver lo que sé de él.|r")
    updateButton:Hide()
    measureButton:Hide()
  else
    detailText:SetText(DetailFor(row))
    if state.tab == "crafts" then updateButton:Show() else updateButton:Hide() end
    if state.tab == "farms" and row.key and not row.key:find("^medido:") then measureButton:Show() else measureButton:Hide() end
  end
  local height = detailText.GetStringHeight and detailText:GetStringHeight() or nil
  if detailChild and height then detailChild:SetHeight(height + 10) end
  if detailScroll and detailScroll.SetVerticalScroll then detailScroll:SetVerticalScroll(0) end
end

function M.Refresh()
  if not window then return end
  local data = Data()
  local gen = PitiGoldsGenerated
  if data and data.verdict then
    local v = data.verdict
    local lines = { ("|c%s%s|r"):format(STATE_COLORS[v.state] or "ffffffff", v.title or "") }
    for _, line in ipairs(v.lines or {}) do lines[#lines + 1] = line end
    verdictText:SetText(table.concat(lines, "\n"))
  else
    verdictText:SetText("|cffaaaaaaEl motor aún no ha calculado los métodos.|r\nAbre vigilar.cmd en el PC, pulsa Exportar"
      .. " y, cuando termine, haz /reload.")
  end
  local made = type(gen) == "table" and gen.generatedAt or 0
  local scan = type(gen) == "table" and gen.lastScan or nil
  local fresh = ("Calculado %s · último escaneo de la subasta %s"):format(Ago(made), Ago(scan))
  if not scan or time() - scan > 12 * 3600 then
    fresh = fresh .. " · |cffff8040escanea la subasta y pulsa Exportar para recalcular|r"
  end
  freshText:SetText(fresh)

  for name, button in pairs(tabButtons) do
    if button.LockHighlight then
      if name == state.tab then button:LockHighlight() else button:UnlockHighlight() end
    end
  end
  local columns = COLUMNS[state.tab]
  local hx = 0
  for i, header in ipairs(headerButtons) do
    local col = columns[i]
    header:ClearAllPoints()
    header:SetPoint("TOPLEFT", header:GetParent(), "TOPLEFT", hx, 0)
    if col then
      hx = hx + col.width
      header:SetWidth(col.width)
      local arrow = state.sort == col.key and (state.desc and " ^" or " v") or ""
      header.label:SetText(col.title .. arrow)
      header.key = col.key
      header:Show()
    else
      header:Hide()
    end
  end

  local rows = Rows()
  state.offset = math.max(0, math.min(state.offset, #rows - ROWS))
  for i, frame in ipairs(rowFrames) do
    local row = rows[i + state.offset]
    if row then
      if state.tab == "crafts" and row._color == nil then
        local _, known = M.CraftSteps(row)
        row._color = known and "verde" or row.color
        row._crafter = known and Crafters(row)[1] or nil
      end
      local cells = state.tab == "farms" and FarmCells(row) or CraftCells(row)
      local x = 0
      for c, cell in ipairs(frame.cells) do
        local col = columns[c]
        if col then
          cell:ClearAllPoints()
          cell:SetPoint("LEFT", frame, "LEFT", x + 4, 0)
          cell:SetWidth(col.width - 8)
          cell:SetText(cells[c] or "")
          cell:Show()
          x = x + col.width
        else
          cell:Hide()
        end
      end
      frame.key = row.key or row.recipe
      if frame.selected then
        if frame.key == state.selected then frame.selected:Show() else frame.selected:Hide() end
      end
      frame:Show()
    else
      frame.key = nil
      frame:Hide()
    end
  end
  ShowDetail()
end

function M.SetTab(tab)
  state.tab, state.offset, state.selected, state.sort, state.desc = tab, 0, nil, nil, false
  if tab == "farms" then
    local data = Data()
    state.selected = data and data.verdict and data.verdict.best or nil
  end
  M.Refresh()
end

function M.Select(index)
  local row = Rows()[index]
  state.selected = row and (row.key or row.recipe) or nil
  M.Refresh()
end

function M.DetailText()
  return detailText and detailText:GetText() or ""
end

function M.Update()
  for _, row in ipairs(Data() and Data().crafts or {}) do
    row._color, row._crafter = nil, nil
  end
  if ns.ScanCarried then pcall(ns.ScanCarried) end
  M.Refresh()
end

local function Scroll(delta)
  state.offset = state.offset - delta
  M.Refresh()
end

local function CreateWindow()
  window = CreateFrame("Frame", "PitiGoldsMethods", UIParent, "BackdropTemplate")
  window:SetSize(WIDTH, HEIGHT)
  window:SetPoint("CENTER")
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
  if UISpecialFrames then table.insert(UISpecialFrames, "PitiGoldsMethods") end

  local title = window:CreateFontString(nil, "OVERLAY", "GameFontNormal")
  title:SetPoint("TOPLEFT", 12, -10)
  title:SetText("PitiGolds: métodos")
  local close = CreateFrame("Button", nil, window, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", -2, -2)
  close:SetScript("OnClick", function() window:Hide() end)

  verdictText = window:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  verdictText:SetPoint("TOPLEFT", 12, -30)
  verdictText:SetWidth(WIDTH - 24)
  verdictText:SetJustifyH("LEFT")
  verdictText:SetJustifyV("TOP")
  verdictText:SetHeight(92)

  freshText = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  freshText:SetPoint("TOPLEFT", 12, -124)
  freshText:SetWidth(WIDTH - 24)
  freshText:SetJustifyH("LEFT")

  local x = 12
  for _, tab in ipairs({ { "farms", "Farmeos" }, { "crafts", "Crafteos" } }) do
    local b = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    b:SetSize(100, 22)
    b:SetPoint("TOPLEFT", x, -140)
    b:SetText(tab[2])
    b:SetScript("OnClick", function() M.SetTab(tab[1]) end)
    tabButtons[tab[1]] = b
    x = x + 104
  end

  local list = CreateFrame("Frame", nil, window)
  list:SetPoint("TOPLEFT", 12, -168)
  list:SetSize(WIDTH - 24, ROW_HEIGHT * (ROWS + 1))
  list:EnableMouseWheel(true)
  list:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)

  for i = 1, 6 do
    local h = CreateFrame("Button", nil, list)
    h:SetHeight(ROW_HEIGHT)
    h.label = h:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    h.label:SetPoint("LEFT", 4, 0)
    h:SetScript("OnClick", function(self)
      if state.sort == self.key then
        state.desc = not state.desc
      else
        state.sort, state.desc = self.key, false
      end
      M.Refresh()
    end)
    headerButtons[i] = h
  end

  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(WIDTH - 24, ROW_HEIGHT)
    row:SetPoint("TOPLEFT", 0, -ROW_HEIGHT * i)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.selected = row:CreateTexture(nil, "BACKGROUND")
    if row.selected then
      row.selected:SetAllPoints()
      row.selected:SetColorTexture(1, 0.82, 0, 0.15)
      row.selected:Hide()
    end
    row.cells = {}
    for c = 1, 6 do
      local cell = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
      cell:SetJustifyH("LEFT")
      if cell.SetWordWrap then cell:SetWordWrap(false) end
      row.cells[c] = cell
    end
    row:SetScript("OnClick", function(self)
      state.selected = self.key
      M.Refresh()
    end)
    row:EnableMouseWheel(true)
    row:SetScript("OnMouseWheel", function(_, delta) Scroll(delta) end)
    rowFrames[i] = row
  end

  local detailTop = -168 - ROW_HEIGHT * (ROWS + 1) - 8
  detailScroll = CreateFrame("ScrollFrame", nil, window)
  detailScroll:SetPoint("TOPLEFT", 12, detailTop)
  detailScroll:SetPoint("BOTTOMRIGHT", -12, 38)
  detailChild = CreateFrame("Frame", nil, detailScroll)
  detailChild:SetSize(WIDTH - 30, 400)
  detailScroll:SetScrollChild(detailChild)
  detailScroll:EnableMouseWheel(true)
  detailScroll:SetScript("OnMouseWheel", function(self, delta)
    local max = math.max(0, (detailChild:GetHeight() or 0) - (self:GetHeight() or 0))
    local current = self:GetVerticalScroll() or 0
    self:SetVerticalScroll(math.max(0, math.min(max, current - delta * 40)))
  end)
  detailText = detailChild:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
  detailText:SetPoint("TOPLEFT", 0, 0)
  detailText:SetWidth(WIDTH - 34)
  detailText:SetJustifyH("LEFT")
  detailText:SetJustifyV("TOP")
  if detailText.SetSpacing then detailText:SetSpacing(2) end

  updateButton = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  updateButton:SetSize(110, 22)
  updateButton:SetPoint("BOTTOMRIGHT", -12, 10)
  updateButton:SetText("Actualizar")
  updateButton:SetScript("OnClick", M.Update)

  measureButton = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
  measureButton:SetSize(140, 22)
  measureButton:SetPoint("BOTTOMRIGHT", -12, 10)
  measureButton:SetText("Medir este farmeo")
  measureButton:SetScript("OnClick", function()
    if state.selected then
      PitiGoldsDB.farmLabel = state.selected
      ns.Print("farmeando: " .. state.selected .. ". Cuando acabes: /pg farmeo fin")
      if ns.RefreshUI then ns.RefreshUI() end
    end
  end)
end

function M.Open(tab)
  if not window then CreateWindow() end
  window:Show()
  M.SetTab(tab or state.tab)
end

function M.Toggle()
  if window and window:IsShown() then
    window:Hide()
  else
    M.Open("farms")
  end
end

ns.Command("metodos", "abre la ventana de métodos: el mejor farmeo y los crafteos", function()
  M.Open("farms")
end)

ns.On("NEW_RECIPE_LEARNED", function()
  if window and window:IsShown() then ns.Debounce("methods", 2, M.Update) end
end)
