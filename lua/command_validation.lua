-- Shared wire-shape predicates; game adapters provide legal commands, IDs and codecs.
local M = {}
function M.integer(value, low, high)
    return type(value)=="number" and value%1==0 and value>=low and value<=high
end
function M.text(value, maximum, empty)
    return type(value)=="string" and #value<=maximum and (empty or #value>0)
end
function M.array(value, minimum, maximum, check)
    if type(value)~="table" or getmetatable(value)~=nil or #value<minimum or #value>maximum then return false end
    local count=0
    for index,item in pairs(value) do
        if not M.integer(index,1,#value) or not check(item) then return false end
        count=count+1
    end
    return count==#value
end
return M
