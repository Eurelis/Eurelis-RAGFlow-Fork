import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useParams } from 'react-router';

import {
  LucideArrowLeft,
  LucideCheckCircle,
  LucideChevronLeft,
  LucideChevronRight,
  LucideDot,
} from 'lucide-react';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Routes } from '@/routes';

import { RAGFlowAvatar } from '@/components/ragflow-avatar';
import Spotlight from '@/components/spotlight';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';

import {
  addTenantMember,
  getUserDetails,
  listTenants,
  listUserTenants,
  removeTenantMember,
  updateTenantMemberRole,
} from '@/services/admin-service';
import EnterpriseFeature from './components/enterprise-feature';
import { parseBooleanish } from './utils';

function matchAvailableFilter(query: string) {
  const q = query.toLowerCase().trim();
  return (item: AdminService.ListTenantsItem) =>
    !q ||
    item.owner_email.toLowerCase().includes(q) ||
    item.owner_nickname.toLowerCase().includes(q);
}

function matchJoinedFilter(query: string) {
  const q = query.toLowerCase().trim();
  return (item: AdminService.UserTenantMembership) =>
    !q ||
    item.email.toLowerCase().includes(q) ||
    item.nickname.toLowerCase().includes(q);
}

function AvailableTeamRow({
  team,
  checked,
  onToggle,
}: {
  team: AdminService.ListTenantsItem;
  checked: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => onToggle(team.tenant_id)}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={() => onToggle(team.tenant_id)}
        onClick={(e) => e.stopPropagation()}
      />
      <RAGFlowAvatar name={team.owner_email} />
      <div className="flex flex-col min-w-0 grow">
        <span className="text-sm truncate">{team.owner_email}</span>
        {team.owner_nickname && (
          <span className="text-xs text-text-secondary truncate">
            {team.owner_nickname}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <Badge variant="outline" className="text-xs">
          {team.member_count}
        </Badge>
      </div>
    </div>
  );
}

function JoinedTeamRow({
  team,
  checked,
  onToggle,
  memberCount,
  onValidate,
}: {
  team: AdminService.UserTenantMembership;
  memberCount?: number;
  checked: boolean;
  onToggle: (id: string) => void;
  onValidate: (id: string) => void;
}) {
  return (
    <div
      className="flex items-center gap-3 px-3 py-2 rounded-md cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => onToggle(team.tenant_id)}
    >
      <Checkbox
        checked={checked}
        onCheckedChange={() => onToggle(team.tenant_id)}
        onClick={(e) => e.stopPropagation()}
      />
      <RAGFlowAvatar avatar={team.avatar} name={team.email} />
      <div className="flex flex-col min-w-0 grow">
        <span className="text-sm truncate">{team.email}</span>
        {team.nickname && (
          <span className="text-xs text-text-secondary truncate">
            {team.nickname}
          </span>
        )}
      </div>
      <div
        className="flex items-center gap-1 shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        {memberCount !== undefined && (
          <Badge variant="outline" className="text-xs">
            {memberCount}
          </Badge>
        )}
        {team.role !== 'normal' && (
          <Badge variant="secondary" className="text-xs">
            {team.role}
          </Badge>
        )}
        {team.role === 'invite' && (
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            onClick={() => onValidate(team.tenant_id)}
          >
            <LucideCheckCircle className="size-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}

function AdminUserTeam() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams();
  const queryClient = useQueryClient();

  const [leftFilter, setLeftFilter] = useState('');
  const [rightFilter, setRightFilter] = useState('');
  const [selectedLeft, setSelectedLeft] = useState<Set<string>>(new Set());
  const [selectedRight, setSelectedRight] = useState<Set<string>>(new Set());

  const { data: detail } = useQuery({
    queryKey: ['admin/userDetail', id],
    queryFn: async () => {
      const res = await getUserDetails(id!);
      return res.data.data[0];
    },
    enabled: !!id,
    retry: false,
  });

  const { data: joinedTeams = [] } = useQuery({
    queryKey: ['admin/userTeams', detail?.id],
    queryFn: async () => (await listUserTenants(detail!.id)).data.data,
    enabled: !!detail?.id,
    retry: false,
  });

  const { data: allTenants = [] } = useQuery({
    queryKey: ['admin/listTenants'],
    queryFn: async () => (await listTenants()).data.data,
    retry: false,
  });

  const invalidateTeams = () => {
    queryClient.invalidateQueries({
      queryKey: ['admin/userTeams', detail?.id],
    });
    queryClient.invalidateQueries({ queryKey: ['admin/listTenants'] });
  };

  const addMutation = useMutation({
    mutationFn: async (tenantIds: string[]) => {
      for (const tid of tenantIds) {
        await addTenantMember(tid, detail!.id, 'normal');
      }
    },
    onSuccess: () => {
      invalidateTeams();
      setSelectedLeft(new Set());
    },
  });

  const removeMutation = useMutation({
    mutationFn: async (tenantIds: string[]) => {
      for (const tid of tenantIds) {
        await removeTenantMember(tid, detail!.id);
      }
    },
    onSuccess: () => {
      invalidateTeams();
      setSelectedRight(new Set());
    },
  });

  const validateMutation = useMutation({
    mutationFn: (tenantId: string) =>
      updateTenantMemberRole(tenantId, detail!.id, 'normal'),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['admin/userTeams', detail?.id],
      });
    },
  });

  const joinedTenantIds = useMemo(
    () => new Set(joinedTeams.map((t) => t.tenant_id)),
    [joinedTeams],
  );

  const tenantCountMap = useMemo(
    () => new Map(allTenants.map((t) => [t.tenant_id, t.member_count])),
    [allTenants],
  );

  const availableTeams = useMemo(
    () =>
      allTenants.filter(
        (t) => t.tenant_id !== detail?.id && !joinedTenantIds.has(t.tenant_id),
      ),
    [allTenants, detail?.id, joinedTenantIds],
  );

  const filteredAvailable = useMemo(
    () => availableTeams.filter(matchAvailableFilter(leftFilter)),
    [availableTeams, leftFilter],
  );

  const filteredJoined = useMemo(
    () => joinedTeams.filter(matchJoinedFilter(rightFilter)),
    [joinedTeams, rightFilter],
  );

  const toggleLeft = (tid: string) =>
    setSelectedLeft((prev) => {
      const next = new Set(prev);
      if (next.has(tid)) next.delete(tid);
      else next.add(tid);
      return next;
    });

  const toggleRight = (tid: string) =>
    setSelectedRight((prev) => {
      const next = new Set(prev);
      if (next.has(tid)) next.delete(tid);
      else next.add(tid);
      return next;
    });

  const allLeftChecked =
    filteredAvailable.length > 0 &&
    filteredAvailable.every((t) => selectedLeft.has(t.tenant_id));
  const someLeftChecked = filteredAvailable.some((t) =>
    selectedLeft.has(t.tenant_id),
  );
  const allRightChecked =
    filteredJoined.length > 0 &&
    filteredJoined.every((t) => selectedRight.has(t.tenant_id));
  const someRightChecked = filteredJoined.some((t) =>
    selectedRight.has(t.tenant_id),
  );

  const leftCheckState = allLeftChecked
    ? true
    : someLeftChecked
      ? 'indeterminate'
      : false;
  const rightCheckState = allRightChecked
    ? true
    : someRightChecked
      ? 'indeterminate'
      : false;

  return (
    <section className="px-10 py-5 size-full flex flex-col">
      <nav className="mb-5">
        <Button
          variant="outline"
          className="h-10 px-3 dark:bg-bg-input dark:border-border-button"
          onClick={() => navigate(`${Routes.AdminUserManagement}`)}
        >
          <LucideArrowLeft />
          <span>{t('admin.back')}</span>
        </Button>
      </nav>

      <Card className="!shadow-none relative h-0 basis-0 grow flex flex-col bg-transparent border-0.5 border-border-button overflow-hidden">
        <Spotlight />

        <CardHeader className="pb-6 border-b-0.5 dark:border-border-button shrink-0 space-y-4">
          <h1 className="text-xl font-semibold">{t('setting.joinedTeams')}</h1>
          <div className="flex items-center gap-4 text-base">
            <RAGFlowAvatar
              avatar={detail?.avatar}
              name={detail?.email}
              isPerson
            />
            <span>{detail?.email}</span>
            <Badge
              variant={
                parseBooleanish(detail?.is_active) ? 'success' : 'destructive'
              }
              className="pl-[.5em]"
            >
              <LucideDot className="size-[1em] stroke-[8] mr-1" />
              {t(
                parseBooleanish(detail?.is_active)
                  ? 'admin.active'
                  : 'admin.inactive',
              )}
            </Badge>
            <EnterpriseFeature>
              {() =>
                detail?.role && (
                  <Badge variant="secondary">{detail?.role}</Badge>
                )
              }
            </EnterpriseFeature>
          </div>
        </CardHeader>

        <CardContent className="h-0 basis-0 grow pt-4 flex gap-3 min-h-0">
          {/* Left panel — available teams */}
          <div className="flex-1 flex flex-col min-h-0 rounded-md border border-border-button">
            <div className="px-3 py-2 border-b border-border-button shrink-0 space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={leftCheckState}
                  onCheckedChange={(c) => {
                    if (c === true)
                      setSelectedLeft(
                        new Set(filteredAvailable.map((t) => t.tenant_id)),
                      );
                    else setSelectedLeft(new Set());
                  }}
                />
                <span className="text-sm font-medium">
                  {t('admin.teamsNotJoined')}
                </span>
                <Badge variant="outline" className="ml-auto text-xs">
                  {selectedLeft.size > 0
                    ? `${selectedLeft.size} / ${filteredAvailable.length}`
                    : filteredAvailable.length}
                </Badge>
              </div>
              <Input
                placeholder={t('admin.filterUsers')}
                value={leftFilter}
                onChange={(e) => setLeftFilter(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
            <ScrollArea className="flex-1">
              <div className="p-1">
                {filteredAvailable.length === 0 ? (
                  <p className="text-sm text-text-secondary text-center py-8">
                    —
                  </p>
                ) : (
                  filteredAvailable.map((team) => (
                    <AvailableTeamRow
                      key={team.tenant_id}
                      team={team}
                      checked={selectedLeft.has(team.tenant_id)}
                      onToggle={toggleLeft}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>

          {/* Center controls */}
          <div className="flex flex-col items-center justify-center gap-2 shrink-0 w-28">
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-1 text-xs"
              disabled={selectedLeft.size === 0 || addMutation.isPending}
              title={t('admin.addToTeam')}
              onClick={() => addMutation.mutate([...selectedLeft])}
            >
              {t('admin.addToTeam')}
              <LucideChevronRight className="size-3.5 shrink-0" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full gap-1 text-xs"
              disabled={selectedRight.size === 0 || removeMutation.isPending}
              title={t('admin.removeFromTeam')}
              onClick={() => removeMutation.mutate([...selectedRight])}
            >
              <LucideChevronLeft className="size-3.5 shrink-0" />
              {t('admin.removeFromTeam')}
            </Button>
          </div>

          {/* Right panel — joined teams */}
          <div className="flex-1 flex flex-col min-h-0 rounded-md border border-border-button">
            <div className="px-3 py-2 border-b border-border-button shrink-0 space-y-2">
              <div className="flex items-center gap-2">
                <Checkbox
                  checked={rightCheckState}
                  onCheckedChange={(c) => {
                    if (c === true)
                      setSelectedRight(
                        new Set(filteredJoined.map((t) => t.tenant_id)),
                      );
                    else setSelectedRight(new Set());
                  }}
                />
                <span className="text-sm font-medium">
                  {t('setting.joinedTeams')}
                </span>
                <Badge variant="outline" className="ml-auto text-xs">
                  {selectedRight.size > 0
                    ? `${selectedRight.size} / ${filteredJoined.length}`
                    : filteredJoined.length}
                </Badge>
              </div>
              <Input
                placeholder={t('admin.filterUsers')}
                value={rightFilter}
                onChange={(e) => setRightFilter(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
            <ScrollArea className="flex-1">
              <div className="p-1">
                {filteredJoined.length === 0 ? (
                  <p className="text-sm text-text-secondary text-center py-8">
                    —
                  </p>
                ) : (
                  filteredJoined.map((team) => (
                    <JoinedTeamRow
                      key={team.tenant_id}
                      team={team}
                      memberCount={tenantCountMap.get(team.tenant_id)}
                      checked={selectedRight.has(team.tenant_id)}
                      onToggle={toggleRight}
                      onValidate={(tid) => validateMutation.mutate(tid)}
                    />
                  ))
                )}
              </div>
            </ScrollArea>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

export default AdminUserTeam;
