/* Source rectangles refer to unmodified 1440x900 captures; keep their aspect ratio. */
window.M1_CAPTURE = {
  images: {
    opening: 'm1/opening-purpose.png', map: 'm1/opening-map.png',
    thawBefore: 'm1/thaw-before.png', thawAfter: 'm1/thaw-after.png',
    replyBefore: 'm1/reply-before.png', replyAfter: 'm1/reply-after.png'
  },
  videos: {
    resource: {file:'m1/resource.webm', start:16.5, end:23.5},
    reply: {file:'m1/reply.webm', start:7, end:14}
  },
  crops: {
    opening:[830,85,600,355], map:[664,98,750,570],
    resourceVideo:[0,55,1440,745], chargeAfter:[18,205,228,85],
    floorAfter:[10,730,570,66], replyVideo:[820,80,620,650],
    replyAfter:[883,285,525,200]
  },
  resourceCaption:'同一局：永焰 5 → 4 · 复查地面：有冰 → 无冰'
};
