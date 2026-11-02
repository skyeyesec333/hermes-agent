import { useStore } from '@nanostores/react'
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { atom } from 'nanostores'
import type { ComponentProps } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const request = vi.hoisted(() => vi.fn())
vi.mock('@hermes/plugin-sdk', async () => {
  const { pluginSdkMock, createGroupGateway } = await import('./group-test-utils')
  const gateway = createGroupGateway()
  const { en } = await import('@/i18n/en')
  const { CANONICAL_GROUP_LOCALES } = await import('./canonical-group-locales')
  const { ConfirmDialog } = await import('@/components/ui/confirm-dialog')

  return { ...await pluginSdkMock(gateway.host), atom, useValue: useStore, ConfirmDialog,
    useI18n: () => ({ t: en }),
    usePluginI18n: () => (key: string) => CANONICAL_GROUP_LOCALES.en[key.replace('canonical.', '') as keyof typeof CANONICAL_GROUP_LOCALES.en] ?? key,
    Button: (p: ComponentProps<'button'>) => <button {...p} />,
    Input: (p: ComponentProps<'input'>) => <input {...p} />,
    RowButton: (p: ComponentProps<'button'>) => <button type="button" {...p} />,
    host: { ...gateway.host, requestProfile: request } }
})
import { host } from '@hermes/plugin-sdk'

import { CanonicalGroupList, refreshCanonicalGroupList, registerCanonicalGroup } from './canonical-group-registry'
import type { CanonicalRoom } from './canonical-groups'

beforeEach(() => {
  request.mockReset()
  request.mockImplementation(async (_route, method) => method === 'groups.capabilities'
    ? { driver: true } : method === 'groups.list' ? { rooms: [], next_offset: null } : {})
})
afterEach(() => { cleanup(); request.mockReset(); localStorage.clear(); vi.unstubAllGlobals() })

it('shows a locally minted room in the sidebar list without a manual refresh (#147808)', async () => {
  const rooms: CanonicalRoom[] = []
  request.mockImplementation(async (_route, method) => method === 'groups.capabilities'
    ? { driver: true } : method === 'groups.list' ? { rooms: [...rooms], next_offset: null } : {})
  render(<CanonicalGroupList onOpen={vi.fn()} />)
  await waitFor(() => expect(request.mock.calls.some(call => call[1] === 'groups.list')).toBe(true))
  // The creation path: mint the room, then tell the list to re-read groups.list.
  rooms.push({ room_id: 'new-room', name: 'Newly created room', members: [] })
  const route = { connectionId: host.state.connectionId.get()!, profile: host.state.profile.get()! }
  act(() => {
    registerCanonicalGroup(route, rooms[rooms.length - 1])
    refreshCanonicalGroupList()
  })
  await screen.findByText('Newly created room')
})

it('list discovery itself does not retrigger a reload (registration never bumps the revision)', async () => {
  const rooms: CanonicalRoom[] = [{ room_id: 'r1', name: 'Team', members: [] }]
  request.mockImplementation(async (_route, method) => method === 'groups.capabilities'
    ? { driver: true } : method === 'groups.list' ? { rooms: [...rooms], next_offset: null } : {})
  render(<CanonicalGroupList onOpen={vi.fn()} />)
  await screen.findByText('Team')
  await act(async () => {})
  expect(request.mock.calls.filter(call => call[1] === 'groups.list')).toHaveLength(1)
})
