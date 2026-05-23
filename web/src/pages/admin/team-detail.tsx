import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import {
  LucideArrowLeft,
  LucideCheckCircle,
  LucidePlus,
  LucideTrash2,
} from 'lucide-react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

import { TableEmpty } from '@/components/table-skeleton';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  addTenantMember,
  listTenantMembers,
  listTenants,
  listUsers,
  removeTenantMember,
  updateTenantMemberRole,
} from '@/services/admin-service';

const columnHelper = createColumnHelper<AdminService.TenantMember>();

function AdminTeamDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tenantId } = useParams<{ tenantId: string }>();
  const queryClient = useQueryClient();

  const [addDialogOpen, setAddDialogOpen] = useState(false);
  const [selectedUserId, setSelectedUserId] = useState('');

  const { data: tenantInfo } = useQuery({
    queryKey: ['admin/listTenants'],
    queryFn: async () => (await listTenants()).data.data,
    select: (data) => data.find((t) => t.tenant_id === tenantId),
    retry: false,
  });

  const { data: members = [] } = useQuery({
    queryKey: ['admin/tenantMembers', tenantId],
    queryFn: async () => (await listTenantMembers(tenantId!)).data.data,
    enabled: !!tenantId,
    retry: false,
  });

  const { data: allUsers = [] } = useQuery({
    queryKey: ['admin/listUsers'],
    queryFn: async () => (await listUsers()).data.data,
    retry: false,
  });

  const removeMutation = useMutation({
    mutationFn: (userId: string) => removeTenantMember(tenantId!, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', tenantId],
      });
      queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
    },
  });

  const validateInviteMutation = useMutation({
    mutationFn: (userId: string) =>
      updateTenantMemberRole(tenantId!, userId, 'normal'),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', tenantId],
      });
    },
  });

  const addMutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: string }) =>
      addTenantMember(tenantId!, userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/tenantMembers', tenantId],
      });
      queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
      setAddDialogOpen(false);
      setSelectedUserId('');
    },
  });

  const existingUserIds = new Set(members.map((m) => m.user_id));
  const availableUsers = allUsers.filter(
    (u) => u.id !== tenantId && !existingUserIds.has(u.id),
  );

  const columnDefs = useMemo(
    () => [
      columnHelper.accessor('email', {
        header: t('admin.email'),
        cell: ({ row, cell }) => (
          <div className="flex items-center gap-2">
            <RAGFlowAvatar
              avatar={row.original.avatar}
              name={cell.getValue()}
            />
            <div className="flex flex-col">
              <span>{cell.getValue()}</span>
              {row.original.nickname && (
                <span className="text-xs text-text-secondary">
                  {row.original.nickname}
                </span>
              )}
            </div>
          </div>
        ),
      }),
      columnHelper.accessor('role', {
        header: t('admin.teamMemberRole'),
        cell: ({ cell }) => (
          <Badge variant="secondary">{cell.getValue()}</Badge>
        ),
      }),
      columnHelper.accessor('update_date', {
        header: t('admin.updateDate'),
      }),
      columnHelper.display({
        id: 'actions',
        header: t('admin.actions'),
        cell: ({ row }) => (
          <div className="flex items-center gap-1">
            {row.original.role === 'invite' && (
              <Button
                variant="ghost"
                size="icon"
                title={t('admin.validateInvite')}
                onClick={() =>
                  validateInviteMutation.mutate(row.original.user_id)
                }
              >
                <LucideCheckCircle className="size-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              className="text-destructive hover:text-destructive"
              onClick={() => removeMutation.mutate(row.original.user_id)}
            >
              <LucideTrash2 className="size-4" />
            </Button>
          </div>
        ),
      }),
    ],
    [t, removeMutation, validateInviteMutation],
  );

  const table = useReactTable({
    data: members,
    columns: columnDefs,
    getCoreRowModel: getCoreRowModel(),
    enableSorting: false,
  });

  return (
    <section className="px-10 py-5 size-full flex flex-col">
      <nav className="mb-5">
        <Button
          variant="outline"
          className="h-10 px-3 dark:bg-bg-input dark:border-border-button"
          onClick={() => navigate(Routes.AdminTeams)}
        >
          <LucideArrowLeft />
          <span>{t('admin.back')}</span>
        </Button>
      </nav>

      <Card className="!shadow-none relative h-0 basis-0 grow flex flex-col bg-transparent border-0.5 border-border-button overflow-hidden">
        <Spotlight />

        <CardHeader className="pb-6 border-b-0.5 dark:border-border-button">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <RAGFlowAvatar name={tenantInfo?.owner_email ?? tenantId} />
              <div>
                <div className="font-semibold">
                  {tenantInfo?.owner_email ?? tenantId}
                </div>
                {tenantInfo?.owner_nickname && (
                  <div className="text-sm text-text-secondary">
                    {tenantInfo.owner_nickname}
                  </div>
                )}
                <div className="text-sm text-text-secondary">
                  {members.length} {t('admin.memberCount').toLowerCase()}
                </div>
              </div>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-2"
              onClick={() => setAddDialogOpen(true)}
            >
              <LucidePlus className="size-4" />
              {t('admin.addToTeam')}
            </Button>
          </div>
        </CardHeader>

        <CardContent className="h-0 basis-0 grow pt-4">
          <ScrollArea className="h-full">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id}>
                    {headerGroup.headers.map((header) => (
                      <TableHead key={header.id}>
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows?.length ? (
                  table.getRowModel().rows.map((row) => (
                    <TableRow key={row.id}>
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id}>
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext(),
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                ) : (
                  <TableEmpty columnsLength={columnDefs.length} />
                )}
              </TableBody>
            </Table>
          </ScrollArea>
        </CardContent>
      </Card>

      <Dialog open={addDialogOpen} onOpenChange={setAddDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('admin.addToTeam')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <label className="text-sm font-medium block mb-2">
                {t('admin.user')}
              </label>
              <Select value={selectedUserId} onValueChange={setSelectedUserId}>
                <SelectTrigger>
                  <SelectValue placeholder={t('admin.selectUser')} />
                </SelectTrigger>
                <SelectContent>
                  {availableUsers.map((u) => (
                    <SelectItem key={u.id} value={u.id}>
                      {u.email}
                      {u.nickname ? ` (${u.nickname})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setAddDialogOpen(false)}>
              {t('admin.cancel')}
            </Button>
            <Button
              disabled={!selectedUserId || addMutation.isPending}
              onClick={() =>
                addMutation.mutate({
                  userId: selectedUserId,
                  role: 'normal',
                })
              }
            >
              {t('admin.confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default AdminTeamDetail;
