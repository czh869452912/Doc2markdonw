function Image(image)
  local axis, value = image.title:match(
    "^md%-convert%-mermaid:([a-z]+)=([0-9]+%.?[0-9]*in)$"
  )
  if (axis == "width" or axis == "height") and value then
    local number = tonumber(value:sub(1, -3))
    if number and number > 0 then
      image.title = ""
      image.attributes[axis] = value
    end
  end
  return image
end
